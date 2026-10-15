"""Render the header IR as C++17-compatible declarations."""
import re

from .sysml import HeaderError

_CPP_KEYWORDS = {
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand", "bitor",
    "bool", "break", "case", "catch", "char", "char8_t", "char16_t", "char32_t",
    "class", "compl", "concept", "const", "consteval", "constexpr", "constinit",
    "const_cast", "continue", "co_await", "co_return", "co_yield", "decltype",
    "default", "delete", "do", "double", "dynamic_cast", "else", "enum", "explicit",
    "export", "extern", "false", "float", "for", "friend", "goto", "if", "inline",
    "int", "long", "mutable", "namespace", "new", "noexcept", "not", "not_eq",
    "nullptr", "operator", "or", "or_eq", "private", "protected", "public",
    "register", "reinterpret_cast", "requires", "return", "short", "signed", "sizeof",
    "static", "static_assert", "static_cast", "struct", "switch", "template", "this",
    "thread_local", "throw", "true", "try", "typedef", "typeid", "typename", "union",
    "unsigned", "using", "virtual", "void", "volatile", "wchar_t", "while", "xor",
    "xor_eq",
}
_SCALARS = {
    "ScalarValues::Integer": "std::int64_t",
    "ScalarValues::Natural": "std::uint64_t",
    "ScalarValues::Real": "double",
    "ScalarValues::Boolean": "bool",
    "ScalarValues::String": "std::string",
}


def _identifier(value):
    value = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not value:
        raise HeaderError("cannot generate a C++ identifier from an empty name")
    if value[0].isdigit():
        value = "_" + value
    if value in _CPP_KEYWORDS:
        value += "_"
    return value


def _path(value):
    return tuple(_identifier(part) for part in value.lstrip(":").split("::") if part)


def _namespaces(namespace, path=()):
    current = path + ((_identifier(namespace.name),) if namespace.name else ())
    yield current, namespace
    for child in namespace.namespaces:
        yield from _namespaces(child, current)


def _records(namespace, path=()):
    for child in namespace.namespaces:
        yield from _records(child, path + (_identifier(child.name),))
    for record in namespace.records:
        yield from _record_paths(record, path)


def _record_paths(record, path):
    current = path + (_identifier(record.name),)
    yield current, record
    for nested in record.nested:
        yield from _record_paths(nested, current)


class _CppRenderer:
    def __init__(self, module):
        self.module = module
        self.records = dict(_records(module.root))
        self._record_names = {path: record for path, record in self.records.items()}

    def _resolve_record(self, value, namespace_path, owner_path):
        if value in _SCALARS:
            return None
        raw = _path(value)
        if not raw:
            return None
        candidates = [raw]
        if value.startswith("::"):
            candidates = [raw]
        else:
            candidates = [
                owner_path + raw,
                namespace_path + raw,
                raw,
            ]
        for candidate in candidates:
            if candidate in self._record_names:
                return candidate
        return None

    def _type(self, type_name, field, namespace_path, owner_path):
        scalar = _SCALARS.get(type_name)
        if scalar is None:
            resolved = self._resolve_record(type_name, namespace_path, owner_path)
            if resolved is not None:
                if resolved[:len(owner_path)] == owner_path:
                    scalar = "::".join(resolved[len(owner_path):])
                elif resolved[:len(namespace_path)] == namespace_path:
                    scalar = "::".join(resolved[len(namespace_path):])
                else:
                    scalar = "::" + "::".join(resolved)
            else:
                scalar = "::".join(_path(type_name))
        if (field.upper is not None and field.lower == field.upper
                and field.lower != 1):
            scalar = f"std::array<{scalar}, {field.lower}>"
        elif field.lower == 0 and field.upper == 1:
            scalar = f"std::optional<{scalar}>"
        elif field.upper is None or field.lower != field.upper:
            scalar = f"std::vector<{scalar}>"
        return scalar

    def _base(self, value, namespace_path, owner_path):
        resolved = self._resolve_record(value, namespace_path, owner_path)
        if resolved is not None:
            if resolved[:len(namespace_path)] == namespace_path:
                return "::".join(resolved[len(namespace_path):])
            return "::" + "::".join(resolved)
        return "::".join(_path(value))

    def _ordered_records(self):
        ordered = []
        visiting = set()
        visited = set()

        def nested_records(record, path):
            yield record, path
            for child in record.nested:
                yield from nested_records(child, path + (_identifier(child.name),))

        def root_record(path):
            while path[:-1] in self._record_names:
                path = path[:-1]
            return path

        def visit(path):
            if path in visited:
                return
            if path in visiting:
                raise HeaderError(
                    f"cyclic by-value or inheritance dependency involving {'::'.join(path)}")
            visiting.add(path)
            namespace_path = path[:-1]
            record = self._record_names[path]
            for member, owner_path in nested_records(record, path):
                for base in member.bases:
                    dependency = self._resolve_record(base, namespace_path, owner_path)
                    if dependency is not None:
                        dependency_root = root_record(dependency)
                        if dependency_root != path:
                            visit(dependency_root)
                for field in member.fields:
                    dependency = self._resolve_record(field.type_name, namespace_path, owner_path)
                    if dependency == owner_path:
                        raise HeaderError(
                            f"{'::'.join(owner_path)} contains itself by value")
                    if dependency is not None:
                        dependency_root = root_record(dependency)
                        if dependency_root != path:
                            visit(dependency_root)
            visiting.remove(path)
            visited.add(path)
            ordered.append((path, record))

        for path in self._record_names:
            if path[:-1] not in self._record_names:
                visit(path)
        return ordered

    def _open_namespace(self, path, lines):
        if path:
            lines.append(f"namespace {'::'.join(path)} {{")

    @staticmethod
    def _close_namespace(path, lines):
        if path:
            lines.append("}")

    def _render_record(self, record, path, namespace_path, indent=0):
        pad = " " * indent
        bases = [
            f"public {self._base(base, namespace_path, path)}"
            for base in record.bases
        ]
        signature = f"{pad}struct {_identifier(record.name)}"
        if bases:
            signature += " : " + ", ".join(bases)
        lines = [signature + " {"]
        for nested in record.nested:
            lines.extend(self._render_record(
                nested, path + (_identifier(nested.name),), namespace_path, indent + 4))
        for item in record.fields:
            field_type = self._type(item.type_name, item, namespace_path, path)
            lines.append(f"{pad}    {field_type} {_identifier(item.name)}{{}};")

        layout_base = next((
            self._resolve_record(base, namespace_path, path)
            for base in record.bases
            if self._resolve_record(base, namespace_path, path) is not None
        ), None)
        layout_base_type = self._base("::".join(layout_base), namespace_path, path) \
            if layout_base else None
        layout_bases = f" : {layout_base_type}::kaitai_layout" if layout_base_type else ""
        lines.append(f"{pad}    struct kaitai_layout{layout_bases} {{")
        lines.append(f"{pad}        static constexpr bool has_size = "
                     f"{'true' if record.bits is not None else 'false'};")
        if record.bits is not None:
            lines.append(f"{pad}        static constexpr std::size_t size_bits = {record.bits};")
        for item in record.fields:
            name = _identifier(item.name)
            if item.bits is not None:
                lines.append(
                    f"{pad}        static constexpr std::size_t {name}_size_bits = {item.bits};")
            if item.offset_bits is not None:
                lines.append(
                    f"{pad}        static constexpr std::size_t {name}_offset_bits = "
                    f"{item.offset_bits};")
        lines.append(f"{pad}    }};")
        lines.append(f"{pad}}};")
        return lines

    def _render_function(self, function, namespace_path):
        outputs = [param for param in function.parameters if param.direction == "out"]
        return_field = outputs[0] if len(outputs) == 1 else None
        return_type = (
            self._type(return_field.type_name, return_field, namespace_path, namespace_path)
            if return_field else "void")
        parameters = []
        for param in function.parameters:
            if param is return_field:
                continue
            value_type = self._type(param.type_name, param, namespace_path, namespace_path)
            if param.direction in ("out", "inout"):
                value_type += "&"
            elif (value_type in ("bool", "double")
                  or value_type.startswith(("std::int", "std::uint"))):
                pass
            else:
                value_type = "const " + value_type + "&"
            parameters.append(f"{value_type} {_identifier(param.name)}")
        signature = f"{return_type} {_identifier(function.name)}"
        parameter_text = ", ".join(parameters)
        if len(signature) + len(parameter_text) + 3 <= 88:
            lines = [f"{signature}({parameter_text}) {{"]
        elif parameters:
            lines = [f"{signature}("]
            lines.extend(
                f"    {parameter}{',' if index < len(parameters) - 1 else ') {'}"
                for index, parameter in enumerate(parameters))
        else:
            lines = [f"{signature}() {{"]
        for connection in function.connections:
            lines.append(f"    // TODO: implement SysML action connection: {connection}")
        lines.append(f'    throw std::logic_error("TODO: implement {function.name}");')
        lines.append("}")
        return lines

    def render(self):
        lines = [
            "#pragma once",
            "#include <array>",
            "#include <cstddef>",
            "#include <cstdint>",
            "#include <optional>",
            "#include <stdexcept>",
            "#include <string>",
            "#include <vector>",
            "",
        ]
        record_namespace = None
        for path, record in self._ordered_records():
            namespace_path = path[:-1]
            if namespace_path != record_namespace:
                if record_namespace is not None:
                    self._close_namespace(record_namespace, lines)
                    lines.append("")
                self._open_namespace(namespace_path, lines)
                record_namespace = namespace_path
            lines.extend(self._render_record(record, path, namespace_path))
            lines.append("")
        if record_namespace is not None:
            self._close_namespace(record_namespace, lines)
            lines.append("")

        for namespace_path, namespace in _namespaces(self.module.root):
            if not namespace.functions:
                continue
            self._open_namespace(namespace_path, lines)
            for function in namespace.functions:
                lines.extend(self._render_function(function, namespace_path))
                lines.append("")
            self._close_namespace(namespace_path, lines)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def render(module):
    """Render one resolved module to a C++ header."""
    return _CppRenderer(module).render()
