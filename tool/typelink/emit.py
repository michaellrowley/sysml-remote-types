"""Renders imported layouts as SysMLv2 and expands TypeLink items in a model."""
import re

from . import c_import, fetch, parser, proto_import, spec as specmod, sysml
from .model import ImportError_

BEGIN = "// typelink:begin (generated from the linked type; edits are overwritten)"
END = "// typelink:end"
_REGION = re.compile(r"[ \t]*// typelink:begin[^\n]*\n.*?// typelink:end[ \t]*\n?", re.S)
_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_KEYWORDS = {n[1:-1] for n in sysml.SysMLv2Lexer.literalNames if n and re.fullmatch(r"'[a-z]+'", n)}


def quote(name):
    return name if _IDENT.match(name) and name not in _KEYWORDS else "'" + name.replace("'", "\\'") + "'"


def _mult(m):
    if (m.lower, m.upper) == (1, 1):
        return ""
    if m.upper is None:
        return f"[{m.lower}..*]" if m.lower else "[0..*]"
    if m.lower == m.upper:
        return f"[{m.lower}]"
    return f"[{m.lower}..{m.upper}]"


def _size(bits, ind):
    return f"@DataSize {{ bits = {bits}; }}" if bits is not None else None


def render_members(struct, types, ind, emitted):
    out = []
    for sub in struct.nested:
        if sub.name in emitted:
            continue
        emitted.add(sub.name)
        out.append(f"{ind}item def {quote(sub.name)} {{")
        if sub.bits is not None:
            out.append(f"{ind}    @DataSize {{ bits = {sub.bits}; }}")
        out += render_members(sub, types, ind + "    ", emitted)
        out.append(f"{ind}}}")
    sysml_types = types["sysml"]
    for m in struct.members:
        n, mult = quote(m.name), _mult(m)
        if m.kind == "unresolved":
            out.append(f"{ind}ref item {n} : {quote(m.type_name)}{mult};")
            continue
        head = (f"item {n} : {quote(m.type_name)}{mult}" if m.kind == "struct"
                else f"attribute {n} : {sysml_types[m.kind]}{mult}")
        size = _size(m.bits, ind)
        out.append(f"{ind}{head} {{ {size} }}" if size else f"{ind}{head};")
    return out


def render_region(struct, types, ind):
    lines = [ind + BEGIN]
    size = _size(struct.bits, ind)
    if size:
        lines.append(ind + size)
    lines += render_members(struct, types, ind, set())
    lines.append(ind + END)
    return "\n".join(lines)


def load_layout(link, data_model=None, text=None):
    source = text if text is not None else fetch.fetch(link.uri)
    if link.origin in ("C", "CPP"):
        return c_import.import_c(source, link.element, link.origin, data_model)
    if link.origin == "Protobuf":
        return proto_import.import_proto(source, link.element)
    raise ImportError_(f"no importer for origin {link.origin}")


def expand(text, data_model=None, fetcher=None, warn=lambda m: None):
    """Return text with every TypeLink-bearing definition body fleshed out."""
    types = specmod.load_types()
    tree = sysml.parse(text)
    links = parser.extract(tree)
    edits = {}
    for link in links:
        body = link.definition
        if body is None or body.LBRACE() is None or body.start.start in edits:
            continue
        res = load_layout(link, data_model, fetcher(link.uri) if fetcher else None)
        for w in res.warnings:
            warn(f"{link.element}: {w}")
        first = link.link_ctx.start
        line_start = text.rfind("\n", 0, first.start) + 1
        ind = re.match(r"[ \t]*", text[line_start:]).group(0)
        inner = _REGION.sub("", text[body.start.start + 1:body.stop.stop])
        inner = inner.rstrip() + "\n" if inner.strip() else "\n"
        edits[body.start.start] = (body.stop.stop, "{" + inner + render_region(res.struct, types, ind) + "\n"
                                   + ind[:-4 if len(ind) >= 4 else 0] + "}")
    for start in sorted(edits, reverse=True):
        stop, repl = edits[start]
        text = text[:start] + repl + text[stop + 1:]
    sysml.parse(text)   # the output must itself be valid SysMLv2
    return text
