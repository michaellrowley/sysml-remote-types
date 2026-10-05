"""C / C++ importer: computes the bit layout of a struct/union/class.

Pipeline: tree-sitter parses the source (grammar from the pinned third_party
submodules); `_collect` indexes aggregates, typedefs, enums and #defines;
`_layout` walks the requested aggregate's fields, applying natural-alignment
rules, and returns a language-neutral `model.Struct`. Anything that cannot be
sized (unknown types, non-constant arrays, base classes) is reported as a
warning and makes the enclosing total size unknown (None) rather than guessed.
Not modelled: #pragma pack, __attribute__((packed/aligned)), templates.
"""
import re

from .. import spec as specmod
from ..model import ImportError_, Member, Result, Struct, align_up
from ..treesitter import get_language
from tree_sitter import Parser
from . import Importer, register

# grammar submodules under third_party/ and their exported entry points
_GRAMMARS = {"C": ("tree-sitter-c", "tree_sitter_c"),
             "CPP": ("tree-sitter-cpp", "tree_sitter_cpp")}
_AGG = ("struct_specifier", "union_specifier", "class_specifier")
_INT_SUFFIX = re.compile(r"[uUlL]+$")


def _txt(n):
    return n.text.decode()


class _Importer:
    """One parse of one source file; resolves types and lays out aggregates."""

    def __init__(self, source, origin, model_name, additional_sources=()):
        types = specmod.load_types()
        self.sysml_types = types["sysml"]
        self.scalars = types["c_scalars"]
        self.model = types["data_models"][model_name or types["default_data_model"]]
        self.warnings = []
        parser = Parser(get_language(*_GRAMMARS[origin]))
        self.roots = [parser.parse(text.encode()).root_node
                      for text in (source, *additional_sources)]
        self.aggs = {}       # tag/typedef name -> specifier node
        self.aliases = {}    # typedef name -> (type node, declarator node)
        self.enums = set()   # enum tag/typedef names (laid out as int)
        self.defines = {}    # #define / enumerator name -> replacement text (for array sizes)
        self.cache = {}      # specifier node id -> Struct; also stops recursive types
        for root in self.roots:
            self._collect(root)

    # ---- symbol collection -------------------------------------------------
    def _collect(self, node):
        """Recursively index every named aggregate, typedef, enum and constant.
        setdefault keeps the first definition if a name is declared twice."""
        for n in node.children:
            t = n.type
            if t in _AGG and n.child_by_field_name("body") is not None:
                nm = n.child_by_field_name("name")
                if nm is not None:
                    self.aggs.setdefault(_txt(nm), n)
                self._collect(n.child_by_field_name("body"))
            elif t == "enum_specifier":
                nm = n.child_by_field_name("name")
                if nm is not None:
                    self.enums.add(_txt(nm))
                self._collect_enum(n)
            elif t == "type_definition":
                ty = n.child_by_field_name("type")
                for d in n.children_by_field_name("declarator"):
                    name = self._decl_name(d)
                    if name is None:
                        continue
                    if ty.type in _AGG and ty.child_by_field_name("body") is not None:
                        self.aggs.setdefault(name, ty)
                    elif ty.type == "enum_specifier":
                        self.enums.add(name)
                    else:
                        self.aliases.setdefault(name, (ty, d))
                self._collect(n)
            elif t == "preproc_def":
                nm, val = n.child_by_field_name("name"), n.child_by_field_name("value")
                if nm is not None and val is not None:
                    self.defines[_txt(nm)] = _txt(val).strip()
            else:
                self._collect(n)

    def _collect_enum(self, n):
        """Record enumerators as constants (explicit value, else previous + 1)
        so they can be used as array sizes."""
        body = n.child_by_field_name("body")
        if body is None:
            return
        nxt = 0
        for e in body.named_children:
            if e.type != "enumerator":
                continue
            v = e.child_by_field_name("value")
            val = self._eval(v) if v is not None else nxt
            if val is not None:
                self.defines[_txt(e.child_by_field_name("name"))] = str(val)
                nxt = val + 1

    def _decl_name(self, d):
        """Identifier at the bottom of a (possibly pointer/array) declarator chain."""
        while d is not None:
            if d.type in ("type_identifier", "identifier", "field_identifier"):
                return _txt(d)
            d = d.child_by_field_name("declarator")
        return None

    # ---- constant expressions for array sizes ------------------------------
    def _eval(self, n, depth=0):
        """Evaluate an integer constant expression; None if it is not constant.
        Supports literals, known #defines/enumerators and + - * / << >> with
        parentheses. `depth` bounds macro-expansion cycles."""
        if n is None or depth > 8:
            return None
        t = n.type
        if t == "number_literal":
            try:
                return int(_INT_SUFFIX.sub("", _txt(n)), 0)
            except ValueError:
                return None
        if t == "identifier":
            v = self.defines.get(_txt(n))
            if v is None:
                return None
            # re-parse the macro body as a C expression statement
            sub = Parser(get_language(*_GRAMMARS["C"])).parse((v + ";").encode()).root_node
            e = sub.named_children[0] if sub.named_children else None
            if e is not None and e.type == "expression_statement":
                e = e.named_children[0] if e.named_children else None
            return self._eval(e, depth + 1)
        if t == "parenthesized_expression":
            return self._eval(n.named_children[0], depth + 1)
        if t == "binary_expression":
            a = self._eval(n.child_by_field_name("left"), depth + 1)
            b = self._eval(n.child_by_field_name("right"), depth + 1)
            op = _txt(n.child_by_field_name("operator"))
            if a is None or b is None:
                return None
            try:
                return {"+": a + b, "-": a - b, "*": a * b, "/": a // b if b else None,
                        "<<": a << b, ">>": a >> b}.get(op)
            except (ValueError, OverflowError):
                return None
        return None

    # ---- type resolution ---------------------------------------------------
    def _scalar(self, name):
        """-> (kind, bits) for a scalar named in spec/types.json (fixed-width
        and stdint types, floats, size_t...), or None. Entries whose width is a
        string (e.g. "pointer") are looked up in the active data model."""
        name = name.replace("std::", "")
        if name in self.scalars:
            kind, bits = self.scalars[name]
            return kind, (self.model[bits] if isinstance(bits, str) else bits)
        return None

    def _base_type(self, n):
        """Resolve a type node to ('scalar', kind, bits), ('agg', Struct) or
        ('unresolved', text). Typedefs are followed; enums are sized as int."""
        t = n.type
        if t == "primitive_type" or t == "sized_type_specifier":
            # signedness does not change size, so ignore it
            words = [w for w in _txt(n).split() if w not in ("signed", "unsigned")]
            spelling = " ".join(words) or "int"
            if spelling in ("char", "short", "int", "long", "long long"):
                return ("scalar", "integer", self.model[spelling])
            if spelling == "short int":
                return ("scalar", "integer", self.model["short"])
            if spelling in ("long int",):
                return ("scalar", "integer", self.model["long"])
            if spelling in ("long long int",):
                return ("scalar", "integer", self.model["long long"])
            sc = self._scalar(spelling)
            if sc:
                return ("scalar",) + sc
            return ("unresolved", _txt(n))
        if t in ("type_identifier", "qualified_identifier"):
            name = _txt(n)
            sc = self._scalar(name)
            if sc:
                return ("scalar",) + sc
            if name in self.enums:
                return ("scalar", "integer", self.model["int"])
            if name in self.aliases:
                ty, d = self.aliases[name]
                inner = self._base_type(ty)
                return self._apply_declarator(inner, d)
            if name in self.aggs:
                return ("agg", self._layout(self.aggs[name], name))
            return ("unresolved", name)
        if t in _AGG:
            name = n.child_by_field_name("name")
            if n.child_by_field_name("body") is not None:
                return ("agg", self._layout(n, _txt(name) if name is not None else None))
            if name is not None and _txt(name) in self.aggs:
                return ("agg", self._layout(self.aggs[_txt(name)], _txt(name)))
            return ("unresolved", _txt(name) if name is not None else _txt(n))
        if t == "enum_specifier":
            return ("scalar", "integer", self.model["int"])
        return ("unresolved", _txt(n))

    def _apply_declarator(self, base, d):
        """A typedef of a pointer (typedef T *p_t) is pointer-sized; otherwise unchanged."""
        if d.type == "pointer_declarator":
            return ("scalar", "integer", self.model["pointer"])
        return base

    def _declarator(self, d):
        """Unwrap a declarator -> (name, is_pointer, array size nodes in
        source order, is_function). Function declarators (not pointers) are
        methods/prototypes and are skipped by the caller."""
        pointer = func = False
        dims = []
        while d is not None:
            t = d.type
            if t in ("field_identifier", "identifier", "type_identifier"):
                return _txt(d), pointer, list(reversed(dims)), func and not pointer
            if t in ("pointer_declarator", "reference_declarator"):
                pointer = True
            elif t == "array_declarator":
                dims.append(d.child_by_field_name("size"))
            elif t == "function_declarator":
                func = True
            nxt = d.child_by_field_name("declarator")
            if nxt is None and d.named_children:
                nxt = d.named_children[0]
            d = nxt
        return None, pointer, dims, func and not pointer

    # ---- layout ------------------------------------------------------------
    def _layout(self, spec_node, name):
        """Lay out a struct/union/class specifier and return a Struct.

        `off` is the running bit offset (structs); `size` the largest member
        (unions); `maxalign` the strictest member alignment, which pads the
        total. `unknown` poisons the total once any member's size is unknown.
        """
        key = spec_node.id
        if key in self.cache:
            return self.cache[key]
        st = Struct(name or "anonymous")
        self.cache[key] = st   # registered before recursing so self-referential types terminate
        union = spec_node.type == "union_specifier"
        unknown = False
        off = 0
        maxalign = 8
        size = 0
        body = spec_node.child_by_field_name("body")
        if any(c.type == "base_class_clause" for c in spec_node.children):
            self.warnings.append(f"{st.name}: base classes are not laid out; total size unknown")
            unknown = True
        for f in body.named_children:
            if f.type != "field_declaration":
                continue
            if any(c.type == "storage_class_specifier" and _txt(c) == "static" for c in f.children):
                continue
            ty = f.child_by_field_name("type")
            decls = f.children_by_field_name("declarator")
            bf = next((c for c in f.children if c.type == "bitfield_clause"), None)
            if not decls:
                # anonymous struct/union member: its fields become ours (flatten)
                base = self._base_type(ty)
                if base[0] == "agg" and ty.type in _AGG:
                    sub = base[1]
                    st.members += sub.members
                    st.nested += sub.nested
                    if sub.bits is None:
                        unknown = True
                    else:
                        a = 8
                        off = align_up(off, a) + sub.bits if not union else off
                        size = max(size, sub.bits)
                continue
            for d in decls:
                mname, pointer, dims, func = self._declarator(d)
                if func or mname is None:
                    continue
                base = ("scalar", "integer", self.model["pointer"]) if pointer else self._base_type(ty)
                count, dynamic = 1, False
                for dn in dims:
                    v = self._eval(dn)
                    if v is None:
                        dynamic = True
                    else:
                        count *= v
                if dims and dynamic:
                    self.warnings.append(f"{st.name}.{mname}: array size is not a constant; sized as variable")
                member, bits, align = self._member(mname, base, st)
                if dims:
                    member.lower, member.upper = (0, None) if dynamic else (count, count)
                # bit-field: occupies `width` bits, and starts a new storage unit
                # (of the declared type's size) if it would straddle one; width 0
                # forces alignment to the next unit
                if bf is not None and bits is not None:
                    width = self._eval(bf.named_children[0]) if bf.named_children else None
                    if width is None:
                        unknown = True
                    elif width == 0:
                        off = align_up(off, bits)
                        continue
                    else:
                        if not union and (off % bits) + width > bits:
                            off = align_up(off, bits)
                        member.bits = width
                        st.members.append(member)
                        if union:
                            size = max(size, width)
                        else:
                            off += width
                        maxalign = max(maxalign, align or 8)
                        continue
                st.members.append(member)
                if bits is None or dynamic or unknown:
                    unknown = True
                    continue
                total = bits * count   # arrays: element size x element count
                maxalign = max(maxalign, align)
                if union:
                    size = max(size, total)
                else:
                    off = align_up(off, align) + total
        if unknown:
            st.bits = None
        elif union:
            st.bits = align_up(size, maxalign)
        else:
            st.bits = align_up(off, maxalign)
        return st

    def _member(self, name, base, owner):
        """Build the Member for a resolved type -> (Member, bits, alignment in
        bits). Aggregates are recorded in owner.nested so the emitter can
        define them. Alignment is capped at 128 bits."""
        if base[0] == "scalar":
            _, kind, bits = base
            return Member(name, kind, bits), bits, min(bits, 128)
        if base[0] == "agg":
            sub = base[1]
            if sub not in owner.nested:
                owner.nested.append(sub)
            align = min(self._struct_align(sub), 128) if sub.bits is not None else 8
            return Member(name, "struct", sub.bits, sub.name), sub.bits, align
        self.warnings.append(f"{owner.name}.{name}: unresolved type '{base[1]}'; size unknown")
        return Member(name, "unresolved", None, base[1]), None, 8

    def _struct_align(self, s):
        """Approximate alignment of a nested struct: its widest scalar member."""
        a = 8
        for m in s.members:
            if m.bits:
                a = max(a, min(m.bits, 128) if m.kind != "struct" else 8)
        return a

    def run(self, element):
        """Entry point: lay out the aggregate called `element`."""
        node = self.aggs.get(element)
        if node is None:
            raise ImportError_(f"no struct/union/class named '{element}' found")
        return Result(self._layout(node, element), self.warnings)


class _CImporter(Importer):
    """Shared by C and C++; subclasses only choose the tree-sitter grammar via `origin`."""
    origin = "C"

    def import_type(self, source, element, data_model=None, additional_sources=()):
        return _Importer(source, self.origin, data_model, additional_sources).run(element)


@register("C")
class CImporter(_CImporter):
    origin = "C"


@register("CPP")
class CppImporter(_CImporter):
    origin = "CPP"
