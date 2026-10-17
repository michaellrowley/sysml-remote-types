"""Render the header IR as Verus-compatible Rust declarations."""
import re

from .model import Field
from .sysml import HeaderError

_SCALARS = {
    "ScalarValues::Integer": "i64",
    "ScalarValues::Natural": "u64",
    "ScalarValues::Real": "f64",
    "ScalarValues::Boolean": "bool",
    "ScalarValues::String": "alloc::string::String",
    "u1": "u8",
    "u2": "u16",
    "u4": "u32",
    "u8": "u64",
    "s1": "i8",
    "s2": "i16",
    "s4": "i32",
    "s8": "i64",
    "f4": "f32",
    "f8": "f64",
    "str": "alloc::string::String",
    "bytes": "u8",
}
_KEYWORDS = {
    "as", "async", "await", "break", "const", "continue", "crate", "dyn",
    "else", "enum", "extern", "false", "fn", "for", "if", "impl", "in",
    "let", "loop", "match", "mod", "move", "mut", "pub", "ref", "return",
    "self", "Self", "static", "struct", "super", "trait", "true", "type",
    "unsafe", "use", "where", "while", "yield",
}


def _identifier(value):
    result = re.sub(r"[^A-Za-z0-9_]", "_", value)
    if not result:
        raise HeaderError("cannot generate a Rust identifier from an empty name")
    if result[0].isdigit():
        result = "_" + result
    if result in _KEYWORDS:
        result += "_"
    return result


def _snake(value):
    value = _identifier(value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return _identifier(re.sub(r"_+", "_", value).lower())


def _pascal(value):
    parts = re.findall(r"[A-Za-z0-9]+", value)
    if not parts:
        raise HeaderError("cannot generate a Rust type name from an empty name")
    result = "".join(part[:1].upper() + part[1:] for part in parts)
    if result[0].isdigit():
        result = "_" + result
    return _identifier(result)


def _namespace_path(namespace, path=()):
    current = path + ((_identifier(namespace.name),) if namespace.name else ())
    yield current, namespace
    for child in namespace.namespaces:
        yield from _namespace_path(child, current)


def _record_paths(record, path):
    current = path + (_identifier(record.name),)
    yield current, record
    for nested in record.nested:
        yield from _record_paths(nested, current)


def _all_records(namespace, path=()):
    for record in namespace.records:
        yield from _record_paths(record, path)
    for child in namespace.namespaces:
        yield from _all_records(child, path + (_identifier(child.name),))


def _all_enumerations(namespace, path=()):
    for enumeration in namespace.enumerations:
        yield path + (_identifier(enumeration.name),), enumeration
    for child in namespace.namespaces:
        yield from _all_enumerations(child, path + (_identifier(child.name),))


class _RustRenderer:
    def __init__(self, module):
        self.module = module
        self.records = dict(_all_records(module.root))
        self.enumerations = dict(_all_enumerations(module.root))
        self.namespace_paths = {
            path for path, _ in _namespace_path(module.root) if path
        }

    def _resolve(self, value, owner_path):
        if value in _SCALARS:
            return None
        parts = tuple(_identifier(part) for part in value.lstrip(":").split("::") if part)
        if not parts:
            return None
        candidates = [parts] if value.startswith("::") else [
            owner_path[:depth] + parts
            for depth in range(len(owner_path), -1, -1)
        ]
        for candidate in candidates:
            if candidate in self.records or candidate in self.enumerations:
                return candidate
        return None

    def _type_path(self, path, namespace_path):
        if path[:len(namespace_path)] == namespace_path:
            path = path[len(namespace_path):]
            if len(path) > 1:
                return _pascal("".join(path))
            return _pascal(path[0])
        containing_namespace = max(
            (candidate for candidate in self.namespace_paths
             if path[:len(candidate)] == candidate),
            key=len,
            default=(),
        )
        modules = [_snake(part) for part in containing_namespace]
        type_name = _pascal("".join(path[len(containing_namespace):]))
        return "crate::" + "::".join(modules + [type_name])

    def _base_type(self, type_name, owner_path, namespace_path, field):
        if type_name in ("str", "bytes") and field.bits is not None:
            if field.bits % 8:
                raise HeaderError(
                    f"{field.name}: Rust {type_name} fields require a byte-aligned "
                    f"bit width (got {field.bits})")
            element = "u8"
            return f"[{element}; {field.bits // 8}]"
        if type_name.startswith("b") and type_name[1:].isdigit():
            width = int(type_name[1:])
            if width > 64:
                raise HeaderError(
                    f"{field.name}: Rust does not support bit fields wider than "
                    f"64 bits (got {width})")
            return next(f"u{size}" for size in (8, 16, 32, 64) if width <= size)
        if field.alternatives:
            raise HeaderError(f"{field.name}: Rust unions require a named SysML type")
        scalar = _SCALARS.get(type_name)
        if scalar is not None:
            return scalar
        resolved = self._resolve(type_name, owner_path)
        if resolved is not None:
            return self._type_path(resolved, namespace_path)
        return "::".join(_identifier(part) for part in type_name.lstrip(":").split("::"))

    def _field_type(self, field, owner_path, namespace_path=None):
        if namespace_path is None:
            namespace_path = owner_path[:-1]
        value = self._base_type(field.type_name, owner_path, namespace_path, field)
        if field.type_name == "bytes" and field.bits is None:
            value = "alloc::vec::Vec<u8>"
        elif field.lower == 0 and field.upper == 1:
            value = f"Option<{value}>"
            return value
        elif field.upper is not None and field.lower == field.upper and field.lower != 1:
            value = f"[{value}; {field.lower}]"
        elif field.upper is None or field.lower != field.upper:
            value = f"alloc::vec::Vec<{value}>"
        if field.conditional or (field.lower == 0 and field.upper == 1):
            value = f"Option<{value}>"
        return value

    def _render_record(self, record, path, namespace_path, indent, name=None):
        record_name = name or _pascal(record.name)
        lines = [f"{indent}pub struct {record_name} {{"]
        for base in record.bases:
            base_type = self._base_type(
                base, path, namespace_path, Field(name=base, type_name=base))
            lines.append(
                f"{indent}    pub {_snake(base.split('::')[-1])}: {base_type},")
        for field in record.fields:
            field_type = self._field_type(field, path, namespace_path)
            lines.append(f"{indent}    pub {_identifier(field.name)}: {field_type},")
        lines.append(f"{indent}}}")
        layout = []
        if record.bits is not None:
            layout.append(f"{indent}    pub const SIZE_BITS: usize = {record.bits};")
        for field in record.fields:
            field_name = _identifier(field.name).upper()
            if field.offset_bits is not None:
                layout.append(
                    f"{indent}    pub const {field_name}_OFFSET_BITS: usize = "
                    f"{field.offset_bits};")
            if field.bits is not None:
                layout.append(
                    f"{indent}    pub const {field_name}_SIZE_BITS: usize = {field.bits};")
        if layout:
            lines.extend([
                "",
                f"{indent}impl {record_name} {{",
                *layout,
                f"{indent}}}",
            ])
        lines.append("")
        for nested in record.nested:
            nested_path = path + (_identifier(nested.name),)
            lines.extend(self._render_record(
                nested, nested_path, namespace_path, indent,
                name=_pascal(record.name + nested.name)))
        return lines

    def _render_namespace(self, namespace, path=(), indent=""):
        lines = []
        current_path = path + ((_identifier(namespace.name),) if namespace.name else ())
        child_indent = indent + "    "

        for enumeration in namespace.enumerations:
            name = _identifier(enumeration.name)
            lines.append(f"{child_indent}pub enum {_pascal(name)} {{")
            for value in enumeration.values:
                lines.append(f"{child_indent}    {_pascal(value)},")
            lines.append(f"{child_indent}}}")
            lines.append("")

        for record in namespace.records:
            record_path = current_path + (_identifier(record.name),)
            lines.extend(self._render_record(
                record, record_path, current_path, child_indent))

        if namespace.functions:
            lines.append(f"{child_indent}pub trait Actions {{")
            for function in namespace.functions:
                inputs = [field for field in function.parameters
                          if field.direction in ("in", "inout")]
                outputs = [field for field in function.parameters
                           if field.direction in ("out", "inout")]
                params = ["&mut self"] + [
                    f"{_identifier(field.name)}: {self._field_type(field, current_path, current_path)}"
                    for field in inputs
                ]
                if not outputs:
                    result = "()"
                elif len(outputs) == 1:
                    result = self._field_type(outputs[0], current_path, current_path)
                else:
                    result = "(" + ", ".join(
                        self._field_type(field, current_path, current_path) for field in outputs) + ")"
                signature = f"fn {_snake(function.name)}({', '.join(params)})"
                lines.append(
                    f"{child_indent}    {signature} -> {result};" if result != "()"
                    else f"{child_indent}    {signature};")
            lines.append(f"{child_indent}}}")
            lines.append("")

        for child in namespace.namespaces:
            lines.append(f"{child_indent}pub mod {_snake(child.name)} {{")
            lines.extend(self._render_namespace(child, current_path, child_indent))
            lines.append(f"{child_indent}}}")
            lines.append("")
        return lines

    def render(self, declarations_only=False):
        del declarations_only
        lines = [
            "// Generated by typelink header --language rust; do not edit.",
            "use vstd::prelude::*;",
            "",
            "verus! {",
        ]
        for namespace in self.module.root.namespaces:
            lines.append(f"    pub mod {_snake(namespace.name)} {{")
            lines.extend(self._render_namespace(namespace, (), ""))
            lines.append("    }")
            lines.append("")
        if self.module.root.records or self.module.root.enumerations or self.module.root.functions:
            lines.extend(self._render_namespace(self.module.root, (), ""))
        lines.append("}")
        return "\n".join(lines).rstrip() + "\n"


def render(module, declarations_only=False):
    return _RustRenderer(module).render(declarations_only=declarations_only)
