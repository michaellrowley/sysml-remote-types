"""Render the header IR as C11 declarations."""
import hashlib
import re

from .sysml import HeaderError

_SCALARS = {
    "ScalarValues::Integer": ("int64_t", True),
    "ScalarValues::Natural": ("uint64_t", True),
    "ScalarValues::Real": ("double", True),
    "ScalarValues::Boolean": ("bool", True),
    "ScalarValues::String": ("char *", False),
    "u1": ("uint8_t", True),
    "u2": ("uint16_t", True),
    "u4": ("uint32_t", True),
    "u8": ("uint64_t", True),
    "s1": ("int8_t", True),
    "s2": ("int16_t", True),
    "s4": ("int32_t", True),
    "s8": ("int64_t", True),
    "f4": ("float", True),
    "f8": ("double", True),
    "str": ("char *", False),
    "bytes": ("uint8_t", True),
}


def _identifier(value):
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result:
        raise HeaderError("cannot generate a C identifier from an empty name")
    if result[0].isdigit():
        result = "_" + result
    if result in {
        "_Alignas", "_Alignof", "_Atomic", "_Bool", "_Complex", "_Generic",
        "_Imaginary", "_Noreturn", "_Static_assert", "_Thread_local",
        "auto", "break", "case", "char", "const", "continue", "default", "do",
        "double", "else", "enum", "extern", "float", "for", "goto", "if",
        "inline", "int", "long", "register", "restrict", "return", "short",
        "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
        "unsigned", "void", "volatile", "while",
    }:
        result += "_"
    return result


def _record_paths(namespace, path=()):
    for child in namespace.namespaces:
        yield from _record_paths(child, path + (_identifier(child.name),))
    for record in namespace.records:
        yield from _nested_paths(record, path)


def _nested_paths(record, path):
    current = path + (_identifier(record.name),)
    yield current, record
    for child in record.nested:
        yield from _nested_paths(child, current)


class _CRenderer:
    def __init__(self, module):
        self.module = module
        self.records = dict(_record_paths(module.root))

    @staticmethod
    def _c_name(path):
        return "_".join(path)

    def _resolve_record(self, name, namespace_path, owner_path):
        if name in _SCALARS:
            return None
        parts = tuple(_identifier(part) for part in name.lstrip(":").split("::") if part)
        if not parts:
            return None
        candidates = [parts] if name.startswith("::") else [
            owner_path[:depth] + parts
            for depth in range(len(owner_path), -1, -1)
        ]
        return next((candidate for candidate in candidates if candidate in self.records), None)

    def _base_type(self, type_name, namespace_path, owner_path):
        scalar = _SCALARS.get(type_name)
        if scalar:
            return scalar[0]
        if type_name.startswith("b") and type_name[1:].isdigit():
            width = int(type_name[1:])
            size = next((size for size in (8, 16, 32, 64) if width <= size), 64)
            return f"uint{size}_t"
        path = self._resolve_record(type_name, namespace_path, owner_path)
        if path is None:
            return f"struct {self._c_name(tuple(_identifier(part) for part in
                                                type_name.lstrip(':').split('::') if part))}"
        return f"struct {self._c_name(path)}"

    def _declaration(self, field, owner_path, namespace_path, name=None):
        field_name = _identifier(name or field.name)
        if field.upper is not None and field.lower == field.upper == 0:
            raise HeaderError(f"{field.name}: C cannot represent a zero-length array")

        def value_declaration(value_name, indent=""):
            if field.alternatives:
                alternatives = [
                    f"{self._base_type(alt, namespace_path, owner_path)} case_{index};"
                    for index, alt in enumerate(field.alternatives)
                ]
                union = [
                    f"{indent}union {{",
                    *(f"{indent}    {alternative}" for alternative in alternatives),
                    f"{indent}}}",
                ]
                if (field.lower == 0 and field.upper == 1) or (
                        field.upper is not None and field.lower == field.upper):
                    return [f"{union[0]}", *union[1:-1],
                            f"{union[-1]} {value_name}[{field.lower}]"
                            if field.lower not in (0, 1) else f"{union[-1]} {value_name}"]
                if field.upper is None or field.lower != field.upper:
                    return [
                        f"{indent}struct {{",
                        f"{indent}    union {{",
                        *(f"{indent}        {alternative}" for alternative in alternatives),
                        f"{indent}    }} *data;",
                        f"{indent}    size_t length;",
                        f"{indent}}} {value_name}",
                    ]
                return [*union[:-1], f"{union[-1]} {value_name}"]

            if field.type_name in ("str", "bytes") and field.bits is not None:
                element = "char" if field.type_name == "str" else "uint8_t"
                block_size = field.bits // 8
                if block_size == 0:
                    raise HeaderError(f"{field.name}: C cannot represent an empty byte block")
                base = element
                suffix = f"[{block_size}]"
            elif field.type_name == "bytes":
                if field.lower != 1 or field.upper != 1:
                    raise HeaderError(
                        f"{field.name}: repeated dynamic byte blocks are unsupported")
                return [
                    f"{indent}struct {{",
                    f"{indent}    uint8_t *data;",
                    f"{indent}    size_t length;",
                    f"{indent}}} {value_name}",
                ]
            else:
                base = self._base_type(field.type_name, namespace_path, owner_path)
                suffix = ""

            if field.lower == 0 and field.upper == 1:
                pass
            elif field.upper is not None and field.lower == field.upper:
                count = field.lower
                if count != 1:
                    suffix = f"[{count}]" + suffix
            elif field.upper is None or field.lower != field.upper:
                if suffix:
                    return [
                        f"{indent}struct {{",
                        f"{indent}    {base} (*data){suffix};",
                        f"{indent}    size_t length;",
                        f"{indent}}} {value_name}",
                    ]
                return [
                    f"{indent}struct {{",
                    f"{indent}    {base} *data;",
                    f"{indent}    size_t length;",
                    f"{indent}}} {value_name}",
                ]
            return [f"{indent}{base} {value_name}{suffix}"]

        optional = field.conditional or (field.lower == 0 and field.upper == 1)
        if optional:
            value_lines = value_declaration("value", "    ")
            value_lines[-1] += ";"
            return [
                "struct {",
                "    bool has_value;",
                *value_lines,
                f"}} {field_name}",
            ]
        return value_declaration(field_name)

    def _ordered_records(self):
        ordered = []
        visiting = set()
        visited = set()

        def visit(path):
            if path in visited:
                return
            if path in visiting:
                raise HeaderError(
                    f"cyclic by-value or inheritance dependency involving {'::'.join(path)}")
            visiting.add(path)
            record = self.records[path]
            dependencies = list(record.bases)
            for field in record.fields:
                dependencies.append(field.type_name)
                dependencies.extend(field.alternatives)
            for name in dependencies:
                dependency = self._resolve_record(name, path[:-1], path)
                if dependency == path:
                    raise HeaderError(f"{'::'.join(path)} contains itself by value")
                if dependency is not None:
                    visit(dependency)
            visiting.remove(path)
            visited.add(path)
            ordered.append((path, record))

        for path in self.records:
            visit(path)
        return ordered

    def _guard(self):
        names = [self._c_name(path) for path in self.records]

        def add_functions(namespace, path=()):
            current = path + ((_identifier(namespace.name),) if namespace.name else ())
            names.extend(
                self._c_name(current + (_identifier(function.name),))
                for function in namespace.functions)
            for child in namespace.namespaces:
                add_functions(child, current)

        add_functions(self.module.root)
        digest = hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()[:12]
        return f"TYPELINK_GENERATED_{digest.upper()}_H"

    def _render_record(self, record, path, namespace_path, lines):
        name = self._c_name(path)
        lines.append(f"struct {name} {{")
        for base in record.bases:
            base_path = self._resolve_record(base, namespace_path, path)
            base_type = (f"struct {self._c_name(base_path)}" if base_path else
                         self._base_type(base, namespace_path, path))
            lines.append(f"    {base_type} base_{_identifier(base.split('::')[-1])};")
        if not record.bases and not record.fields:
            lines.append("    uint8_t typelink_empty;")
        for field in record.fields:
            declaration = self._declaration(field, path, namespace_path)
            lines.extend(
                f"    {line}" for line in declaration[:-1])
            lines.append(f"    {declaration[-1]};")
        lines.append("};")
        prefix = _identifier(name.upper())
        if record.bits is not None:
            lines.append(f"#define {prefix}_KAITAI_SIZE_BITS {record.bits}")
        for field in record.fields:
            field_prefix = f"{prefix}_{_identifier(field.name.upper())}"
            if field.bits is not None:
                lines.append(f"#define {field_prefix}_KAITAI_SIZE_BITS {field.bits}")
            if field.offset_bits is not None:
                lines.append(
                    f"#define {field_prefix}_KAITAI_OFFSET_BITS {field.offset_bits}")
        lines.append("")

    def _function(self, function, namespace_path):
        parameters = []
        for param in function.parameters:
            base = self._base_type(param.type_name, namespace_path, namespace_path)
            collection = (param.upper is None or param.lower != param.upper
                          or (param.upper is not None and param.upper > 1))
            if param.direction in ("out", "inout") or collection:
                name = _identifier(param.name)
                if base.endswith("*"):
                    qualifier = "const " if param.direction == "in" else ""
                    parameters.append(f"{qualifier}{base.rstrip()}*{name}")
                else:
                    qualifier = "const " if param.direction == "in" else ""
                    parameters.append(f"{qualifier}{base} *{name}")
            elif param.type_name in ("ScalarValues::String", "str"):
                parameters.append(f"const char *{_identifier(param.name)}")
            elif not (_SCALARS.get(param.type_name, (None, False))[1]
                      or re.fullmatch(r"b[0-9]+", param.type_name) is not None):
                parameters.append(f"const {base} *{_identifier(param.name)}")
            else:
                parameters.append(f"{base} {_identifier(param.name)}")
        name = self._c_name(namespace_path + (_identifier(function.name),))
        signature = f"static inline void {name}"
        parameter_text = ", ".join(parameters) or "void"
        if len(signature) + len(parameter_text) + 4 <= 88:
            lines = [f"{signature}({parameter_text}) {{"]
        elif parameters:
            lines = [f"{signature}("]
            lines.extend(
                f"    {parameter}{',' if index < len(parameters) - 1 else ') {'}"
                for index, parameter in enumerate(parameters))
        else:
            lines = [f"{signature}(void) {{"]
        for param in function.parameters:
            lines.append(f"    (void){_identifier(param.name)};")
        for connection in function.connections:
            connection = connection.replace("*/", "* /")
            lines.append(f"    /* TODO: implement SysML action connection: {connection} */")
        lines.extend(("    /* TODO: implement this action. */", "}"))
        return lines

    def render(self):
        guard = self._guard()
        lines = [
            f"#ifndef {guard}",
            f"#define {guard}",
            "#include <stdbool.h>",
            "#include <stddef.h>",
            "#include <stdint.h>",
            "",
        ]
        ordered = self._ordered_records()
        for path, _record in ordered:
            lines.append(f"struct {self._c_name(path)};")
        if ordered:
            lines.append("")
        for path, record in ordered:
            self._render_record(record, path, path[:-1], lines)

        def functions(namespace, path=()):
            current = path + ((_identifier(namespace.name),) if namespace.name else ())
            for function in namespace.functions:
                lines.extend(self._function(function, current))
                lines.append("")
            for child in namespace.namespaces:
                functions(child, current)

        functions(self.module.root)
        lines.append("#endif")
        return "\n".join(lines) + "\n"


def render(module):
    """Render one resolved module to a C header."""
    return _CRenderer(module).render()
