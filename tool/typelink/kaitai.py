"""Generate Kaitai Struct schemas from expanded or native SysMLv2 items."""
from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional, Set, Tuple

from . import sysml

P = sysml.P
_PROTO_VARINT = "protobuf_varint"
_PROTO_VARINT_GROUP = "protobuf_varint_group"
_PROTO_UNKNOWN = "protobuf_unknown"
_PROTO_BYTES = "protobuf_bytes_payload"


class KaitaiError(ValueError):
    pass


@dataclass
class _Field:
    name: str
    type_name: str
    lower: int = 1
    upper: int = 1
    bits: Optional[int] = None
    offset: Optional[int] = None
    signed: Optional[bool] = None
    encoding: Dict[str, str] = field(default_factory=dict)
    mapping: Dict[str, str] = field(default_factory=dict)
    ksy_id: Optional[str] = None


@dataclass(eq=False)
class _Item:
    name: str
    layout: Optional[str] = None
    bits: Optional[int] = None
    fields: List[_Field] = field(default_factory=list)
    children: List["_Item"] = field(default_factory=list)
    ksy_id: Optional[str] = None
    signed_instances: List[Tuple[str, str]] = field(default_factory=list)
    generated_ids: Set[str] = field(default_factory=set)
    message_type_id: Optional[str] = None


def _unquote(value):
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("\\'", "'")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _identifier(value):
    value = _unquote(value)
    result = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if not result:
        raise KaitaiError(f"cannot make a Kaitai identifier from {value!r}")
    if result[0].isdigit():
        result = "t_" + result
    return result


def _metadata_values(feature):
    values = {}
    for assignment in sysml.find_all(feature, P.MetadataBodyFeatureContext):
        key = assignment.ownedRedefinition().getText()
        value = sysml.find_first(assignment, P.ValuePartContext)
        if value is None:
            continue
        raw = value.getText().lstrip("=")
        if raw.startswith(("'", '"')):
            raw = _unquote(raw)
        elif "::" in raw:
            raw = raw.rsplit("::", 1)[1]
        values[key] = raw
    return values


def _metadata(body, name):
    if body is None:
        return {}
    matches = []
    for feature in sysml.find_all(body, P.MetadataFeatureContext):
        if sysml.ancestor(feature, P.DefinitionBodyContext) is not body:
            continue
        declaration = sysml.find_first(feature, P.MetadataFeatureDeclarationContext)
        typing = sysml.find_first(declaration, P.OwnedFeatureTypingContext)
        if typing is not None and typing.getText() == name:
            matches.append(_metadata_values(feature))
    if len(matches) > 1:
        raise KaitaiError(f"duplicate @{name} annotation")
    return matches[0] if matches else {}


def _natural(values, key, required=False):
    raw = values.get(key)
    if raw is None:
        if required:
            raise KaitaiError(f"@{key} value is missing")
        return None
    try:
        result = int(raw)
    except ValueError:
        raise KaitaiError(f"@{key} must be a non-negative integer") from None
    if result < 0:
        raise KaitaiError(f"@{key} must be a non-negative integer")
    return result


def _bool(values, key):
    raw = values.get(key)
    if raw is None:
        return None
    if raw.lower() not in ("true", "false"):
        raise KaitaiError(f"{key} must be true or false")
    return raw.lower() == "true"


def _multiplicity(declaration):
    ranges = list(sysml.find_all(declaration, P.OwnedMultiplicityRangeContext))
    if len(ranges) > 1:
        raise KaitaiError("multi-dimensional multiplicity is not supported")
    if not ranges:
        return 1, 1
    raw = ranges[0].getText()
    if not (raw.startswith("[") and raw.endswith("]")):
        raise KaitaiError(f"invalid multiplicity {raw!r}")
    raw = raw[1:-1]
    if ".." not in raw:
        try:
            count = int(raw)
        except ValueError:
            raise KaitaiError(f"unsupported multiplicity [{raw}]") from None
        if count < 0:
            raise KaitaiError(f"unsupported multiplicity [{raw}]")
        return count, count
    lower_raw, upper_raw = raw.split("..", 1)
    try:
        lower = int(lower_raw)
        upper = None if upper_raw == "*" else int(upper_raw)
    except ValueError:
        raise KaitaiError(f"unsupported multiplicity [{raw}]") from None
    if lower < 0 or (upper is not None and upper < lower):
        raise KaitaiError(f"unsupported multiplicity [{raw}]")
    return lower, upper


def _usage_fields(body):
    for usage in sysml.find_all(body, P.UsageContext):
        if sysml.ancestor(usage, P.DefinitionBodyContext) is not body:
            continue
        declaration = sysml.find_first(usage, P.UsageDeclarationContext)
        if declaration is None:
            raise KaitaiError(f"unsupported feature usage {usage.getText()!r}")
        wrapper = usage.parentCtx
        wrapper_name = type(wrapper).__name__
        if wrapper_name not in ("AttributeUsageContext", "ItemUsageContext"):
            raise KaitaiError(f"unsupported feature usage {usage.getText()!r}")
        type_ctx = sysml.find_first(declaration, P.OwnedFeatureTypingContext)
        if type_ctx is None:
            raise KaitaiError(f"{declaration.getText()}: a data type is required")
        name_ctx = sysml.find_first(declaration, P.IdentificationContext)
        if name_ctx is None:
            raise KaitaiError(f"cannot read feature name from {declaration.getText()!r}")
        scope = sysml.find_first(usage, P.DefinitionBodyContext)
        size = _metadata(scope, "DataSize")
        offset = _metadata(scope, "DataOffset")
        signed = _metadata(scope, "DataSigned")
        encoding = _metadata(scope, "DataEncoding")
        mapping = _metadata(scope, "DataMap")
        lower, upper = _multiplicity(declaration)
        yield _Field(
            name=_unquote(name_ctx.getText()),
            type_name=type_ctx.getText(),
            lower=lower,
            upper=upper,
            bits=_natural(size, "bits"),
            offset=_natural(offset, "bits"),
            signed=_bool(signed, "value"),
            encoding=encoding,
            mapping=mapping,
        )


def _item_from_context(context):
    declaration = sysml.find_first(context, P.DefinitionDeclarationContext)
    if declaration is None:
        raise KaitaiError("item definition has no name")
    name = sysml.decl_name(declaration)
    body = sysml.find_first(context, P.DefinitionBodyContext)
    layout = _metadata(body, "DataLayout").get("kind")
    layout = layout.lower() if layout else None
    size = _metadata(body, "DataSize")
    item = _Item(name=_unquote(name), layout=layout, bits=_natural(size, "bits"))
    if body is None:
        return item
    for child in sysml.find_all(body, P.ItemDefinitionContext):
        if sysml.ancestor(child, P.DefinitionBodyContext) is body:
            item.children.append(_item_from_context(child))
    item.fields = list(_usage_fields(body))
    return item


def _all_items(item):
    yield item
    for child in item.children:
        yield from _all_items(child)


def _find_item(items, name, scope=None):
    target = _unquote(name).split("::")[-1]
    if scope is not None:
        local = [child for child in scope.children if child.name == target]
        if len(local) == 1:
            return local[0]
        if scope.name == target:
            return scope
    matches = [item for item in items if item.name == target]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise KaitaiError(f"type {name!r} is ambiguous; qualify it or rename nested items")
    return None


def _assign_ids(root):
    root.ksy_id = _identifier(root.name)
    names = {}

    def assign(item, parts):
        item.ksy_id = root.ksy_id if item is root else _identifier(
            "__".join((root.name, *parts)))
        if item.ksy_id in names and names[item.ksy_id] is not item:
            raise KaitaiError(f"item names collide after Kaitai normalization: {item.name!r}")
        names[item.ksy_id] = item
        field_ids = set()
        for member in item.fields:
            member.ksy_id = _identifier(member.name)
            if member.ksy_id in field_ids:
                raise KaitaiError(
                    f"{item.name}: feature names collide after Kaitai normalization")
            field_ids.add(member.ksy_id)
        for child in item.children:
            assign(child, (*parts, child.name))

    assign(root, ())


def _scalar_kind(type_name):
    name = _unquote(type_name.split("::")[-1])
    return {
        "Integer": "integer", "Natural": "natural", "Positive": "natural",
        "Real": "real", "Boolean": "boolean", "String": "string",
    }.get(name)


def _repeat_lines(member, lines, indent):
    if member.lower == 1 and member.upper == 1:
        return
    if member.upper is None:
        if member.lower != 0:
            raise KaitaiError(
                f"{member.name}: Kaitai repeat-to-end cannot enforce a minimum count")
        lines.append(f"{indent}repeat: eos")
    elif member.lower == member.upper:
        lines.append(f"{indent}repeat: expr")
        lines.append(f"{indent}repeat-expr: {member.lower}")
    else:
        raise KaitaiError(
            f"{member.name}: bounded variable multiplicity cannot be represented")


def _primitive_type(kind, bits, signed, integer_signedness, field_name):
    if bits is None or bits <= 0:
        raise KaitaiError(f"{field_name}: a positive @DataSize is required")
    if kind in ("integer", "natural"):
        signed = (integer_signedness if signed is None else signed) \
            if kind == "integer" else False
        if bits in (8, 16, 32, 64):
            prefix = "s" if signed else "u"
            return f"{prefix}{bits // 8}", None
        if bits <= 64:
            return f"b{bits}", None
        raise KaitaiError(f"{field_name}: Kaitai integer widths are limited to 64 bits")
    if kind == "real":
        if bits not in (32, 64):
            raise KaitaiError(f"{field_name}: Kaitai supports only 32- and 64-bit reals")
        return f"f{bits // 8}", None
    if kind == "boolean":
        if bits == 8:
            return "u1", None
        if bits <= 64:
            return f"b{bits}", None
        raise KaitaiError(f"{field_name}: boolean widths are limited to 64 bits")
    if kind == "string":
        if bits % 8:
            raise KaitaiError(f"{field_name}: strings must have a byte-aligned @DataSize")
        return "str", bits // 8
    raise KaitaiError(f"{field_name}: unsupported SysML type")


def _seq_lines(item, items, integer_signedness):
    if item.layout == "union":
        if item.bits is None or item.bits <= 0 or item.bits % 8:
            raise KaitaiError(
                f"{item.name}: Kaitai can only emit byte-sized opaque unions")
        return ["  - id: data", f"    size: {item.bits // 8}"]
    if item.layout == "protobuf":
        raise KaitaiError("internal error: Protobuf item passed to struct generator")
    if item.layout not in (None, "struct"):
        raise KaitaiError(f"{item.name}: unsupported DataLayout kind {item.layout!r}")
    cursor = 0
    fields = []
    for index, member in enumerate(item.fields):
        if member.lower == 0 and member.upper is None and index != len(item.fields) - 1:
            raise KaitaiError(f"{item.name}.{member.name}: repeat-to-end must be the last field")
        if item.layout == "struct":
            if member.offset is None:
                raise KaitaiError(
                    f"{item.name}.{member.name}: offset-based layout has no known DataOffset")
            if member.offset < cursor:
                raise KaitaiError(
                    f"{item.name}.{member.name}: DataOffset overlaps the preceding member")
            fields.extend(_padding_for_gap(item, cursor, member.offset, "  "))
            cursor = member.offset
        fields.extend(_render_field(item, member, items, integer_signedness))
        span = _field_span(item, member, items)
        if span is None:
            cursor = None
            if index != len(item.fields) - 1:
                raise KaitaiError(f"{item.name}.{member.name}: repeat-to-end must be last")
        elif cursor is not None:
            cursor += span
    if item.layout == "struct" and item.bits is not None:
        if cursor is None:
            raise KaitaiError(f"{item.name}: a variable-length struct cannot have DataSize")
        if item.bits < cursor:
            raise KaitaiError(f"{item.name}: DataSize is smaller than its last field")
        fields.extend(_padding_for_gap(item, cursor, item.bits, "  "))
    elif item.bits is not None and cursor is not None:
        if item.bits < cursor:
            raise KaitaiError(f"{item.name}: DataSize is smaller than its packed fields")
        fields.extend(_padding_for_gap(item, cursor, item.bits, "  "))
    return fields


def _field_span(item, member, items):
    if member.upper is None:
        return None
    count = member.lower if member.lower == member.upper else None
    if count is None:
        return None
    type_item = _find_item(items, member.type_name, item)
    bits = member.bits if member.bits is not None else (type_item.bits if type_item else None)
    return bits * count if bits is not None else None


def _render_field(item, member, items, integer_signedness):
    if member.encoding:
        raise KaitaiError(
            f"{item.name}.{member.name}: Protobuf wire metadata is only valid "
            "inside a Protobuf item")
    type_item = _find_item(items, member.type_name, item)
    scalar = _scalar_kind(member.type_name)
    if type_item is not None:
        if member.signed is not None:
            raise KaitaiError(f"{member.name}: @DataSigned cannot annotate an item type")
        field_type = type_item.ksy_id
        bits = member.bits if member.bits is not None else type_item.bits
        if bits is not None and type_item.bits is not None and bits != type_item.bits:
            raise KaitaiError(
                f"{item.name}.{member.name}: @DataSize {bits} conflicts with "
                f"type {type_item.name} size {type_item.bits}")
        size = None
    elif scalar is not None:
        field_type, size = _primitive_type(
            scalar, member.bits, member.signed, integer_signedness,
            f"{item.name}.{member.name}")
        bits = member.bits
    else:
        raise KaitaiError(
            f"{item.name}.{member.name}: unresolved or unsupported type "
            f"{member.type_name!r}")
    if bits is None:
        raise KaitaiError(f"{item.name}.{member.name}: size is unknown")
    lines = [f"  - id: {member.ksy_id}", f"    type: {field_type}"]
    if size is not None:
        lines.append(f"    size: {size}")
    _repeat_lines(member, lines, "    ")
    if field_type.startswith("b") and member.signed:
        if member.lower != 1 or member.upper != 1:
            raise KaitaiError(
                f"{member.name}: signed arrays of nonstandard bit widths are unsupported")
        sign = 1 << (bits - 1)
        modulus = 1 << bits
        item.signed_instances.append(
            (member.ksy_id + "_signed",
             f"{member.ksy_id} >= {sign} ? {member.ksy_id} - {modulus} : {member.ksy_id}"))
    return lines


def _padding_for_gap(item, start, end, indent):
    gap = end - start
    if gap < 0:
        raise KaitaiError(f"{item.name}: negative padding gap")
    if gap == 0:
        return []
    names = {member.ksy_id for member in item.fields}
    chunks_needed = (gap + 63) // 64 if start % 8 or gap % 8 else 0
    index = 0
    while (f"padding_{index}" in names
           or f"padding_{index}" in item.generated_ids
           or any(f"padding_{index}_{part}" in names
                  or f"padding_{index}_{part}" in item.generated_ids
                  for part in range(chunks_needed))):
        index += 1
    field_id = f"padding_{index}"
    item.generated_ids.add(field_id)
    if start % 8 == 0 and gap % 8 == 0:
        return [f"{indent}- id: {field_id}", f"{indent}  size: {gap // 8}"]
    lines = []
    while gap:
        chunk = min(gap, 64)
        chunk_id = f"{field_id}_{len(lines) // 2}"
        item.generated_ids.add(chunk_id)
        lines.extend((f"{indent}- id: {chunk_id}", f"{indent}  type: b{chunk}"))
        gap -= chunk
    return lines


def _message_contexts(tree):
    return [
        context for context in sysml.find_all(tree, P.ItemDefinitionContext)
        if sysml.ancestor(context, P.DefinitionBodyContext) is None
    ]


class _ProtoBuilder:
    def __init__(self, root, items):
        self.root = root
        self.items = items
        self.helpers = {}
        self.message_bodies = {}

    def _register(self, name, body):
        if name in self.helpers and self.helpers[name] != body:
            raise KaitaiError(f"generated Kaitai helper name collision: {name}")
        self.helpers[name] = body
        return name

    def _scalar_payload(self, owner, suffix, source_type, kind):
        primitive = {
            ("fixed32", "float"): "f4",
            ("fixed32", "sfixed32"): "s4",
            ("fixed32", "fixed32"): "u4",
            ("fixed64", "double"): "f8",
            ("fixed64", "sfixed64"): "s8",
            ("fixed64", "fixed64"): "u8",
        }.get((kind, source_type.split(".")[-1]))
        if primitive:
            return primitive
        if kind not in ("varint", "zigzag", "enum"):
            raise KaitaiError(f"unsupported Protobuf wire kind {kind!r}")
        name = _identifier(f"_pb_{owner}_{suffix}")
        source = source_type.split(".")[-1]
        raw = "raw.value"
        if kind == "zigzag" or source in ("sint32", "sint64"):
            expression = f"{raw} % 2 == 0 ? {raw} / 2 : -({raw} / 2) - 1"
        elif source in ("int32", "sint32") or kind == "enum":
            value = f"({raw} % 4294967296)"
            expression = (
                f"{value} >= 2147483648 ? {value} - 4294967296 : {value}")
        elif source == "int64":
            expression = (
                f"{raw} >= 9223372036854775808 ? "
                f"-1 - (18446744073709551615 - {raw}) : {raw}")
        elif source == "bool":
            expression = f"{raw} != 0"
        elif source == "uint32":
            expression = f"{raw} % 4294967296"
        else:
            expression = raw
        body = [
            "seq:",
            "  - id: raw",
            f"    type: {_PROTO_VARINT}",
            "instances:",
            "  value:",
            f'    value: "{expression}"',
        ]
        return self._register(name, body)

    def _length_payload(self, owner, suffix, kind, source_type, target=None):
        name = _identifier(f"_pb_{owner}_{suffix}")
        body = ["seq:", "  - id: length", f"    type: {_PROTO_VARINT}"]
        if kind == "string":
            body.extend(("  - id: value", "    type: str", "    size: length.value"))
        elif kind == "bytes":
            body.extend(("  - id: value", "    size: length.value"))
        elif kind == "message":
            if target is None:
                raise KaitaiError(f"unresolved Protobuf message type {source_type!r}")
            target_id = getattr(target, "message_type_id", None) or target.ksy_id
            body.extend(("  - id: value", f"    type: {target_id}",
                         "    size: length.value"))
        elif kind == "map":
            if target is None:
                raise KaitaiError("Protobuf map entry type was not generated")
            body.extend(("  - id: value", f"    type: {target}",
                         "    size: length.value"))
        else:
            raise KaitaiError(f"unsupported length-delimited Protobuf kind {kind!r}")
        return self._register(name, body)

    def _packed_payload(self, owner, suffix, source_type, kind):
        scalar = self._scalar_payload(owner, suffix + "_element", source_type, kind)
        packed = self._register(
            _identifier(f"_pb_{owner}_{suffix}_values"),
            ["seq:", "  - id: items", f"    type: {scalar}", "    repeat: eos"])
        return self._length_payload(owner, suffix + "_packed", "message",
                                    source_type, _HelperType(packed))

    def _map_type(self, item, member):
        if not member.mapping:
            raise KaitaiError(f"{item.name}.{member.name}: Protobuf map metadata is missing")
        entry_id = _identifier(f"_pb_{item.ksy_id}_{member.ksy_id}_entry")
        fields_id = _identifier(f"_pb_{item.ksy_id}_{member.ksy_id}_entry_field")
        cases = {}
        for number, source_type, suffix in (
            (1, member.mapping.get("key_type"), "key"),
            (2, member.mapping.get("value_type"), "value"),
        ):
            if not source_type:
                raise KaitaiError(f"{item.name}.{member.name}: map entry type is missing")
            declared_kind = (
                member.mapping.get("value_kind") if suffix == "value" else None)
            kind, wire = self._map_value_kind(source_type, declared_kind)
            target = self._find_message(source_type, item) if kind == "message" else None
            payload = self._payload(
                item, member, f"entry_{suffix}", source_type, kind, target)
            cases[number * 8 + wire] = payload
        body = self._field_parser_body(cases)
        self._register(fields_id, body)
        entry_body = [
            "seq:",
            "  - id: fields",
            f"    type: {fields_id}",
            "    repeat: eos",
        ]
        self._register(entry_id, entry_body)
        return entry_id

    def _map_value_kind(self, source_type, declared_kind=None):
        short = _unquote(source_type.split(".")[-1])
        wire = {
            "string": ("string", 2), "bytes": ("bytes", 2),
            "int32": ("varint", 0), "int64": ("varint", 0),
            "uint32": ("varint", 0), "uint64": ("varint", 0),
            "bool": ("varint", 0), "sint32": ("zigzag", 0),
            "sint64": ("zigzag", 0), "fixed32": ("fixed32", 5),
            "sfixed32": ("fixed32", 5), "float": ("fixed32", 5),
            "fixed64": ("fixed64", 1), "sfixed64": ("fixed64", 1),
            "double": ("fixed64", 1),
        }.get(short)
        if wire:
            return wire
        if declared_kind == "enum":
            return "enum", 0
        if declared_kind == "unresolved":
            raise KaitaiError(f"unresolved Protobuf map value type {source_type!r}")
        target = _find_item(self.items, source_type)
        if target:
            return "message", 2
        if declared_kind == "message":
            raise KaitaiError(f"unresolved Protobuf map message type {source_type!r}")
        raise KaitaiError(f"unsupported Protobuf map value type {source_type!r}")

    def _find_message(self, type_name, scope):
        target = _find_item(self.items, type_name, scope)
        if target is None:
            raise KaitaiError(f"unresolved Protobuf message type {type_name!r}")
        return target

    def _payload(self, item, member, suffix, source_type, kind, target):
        owner = item.ksy_id + "_" + member.ksy_id
        if kind in ("varint", "zigzag", "fixed32", "fixed64", "enum"):
            return self._scalar_payload(owner, suffix, source_type, kind)
        if kind in ("string", "bytes", "message", "map"):
            return self._length_payload(owner, suffix, kind, source_type, target)
        if kind == "group":
            raise KaitaiError(
                f"{item.name}.{member.name}: Protobuf groups are not supported")
        raise KaitaiError(f"{item.name}.{member.name}: unsupported Protobuf kind {kind!r}")

    def _field_parser_body(self, cases):
        lines = [
            "seq:",
            "  - id: tag",
            f"    type: {_PROTO_VARINT}",
            "  - id: value",
            "    type:",
            "      switch-on: tag.value",
            "      cases:",
        ]
        for tag in sorted(cases):
            lines.append(f"        {tag}: {cases[tag]}")
        lines.append(f"        _: {_PROTO_UNKNOWN}(tag.value % 8)")
        return lines

    def build(self):
        root_is_referenced = False
        self._register(_PROTO_VARINT, [
            "seq:",
            "  - id: groups",
            f'    type: "{_PROTO_VARINT_GROUP}(_index, _index != 0 ? '
            'groups[_index - 1].interm_value : 0, _index != 0 ? '
            'groups[_index - 1].multiplier * 128 : 1)"',
            "    repeat: until",
            "    repeat-until: not _.has_next",
            "instances:",
            "  len:",
            "    value: groups.size",
            "  value:",
            "    value: groups.last.interm_value",
        ])
        self._register(_PROTO_VARINT_GROUP, [
            "params:",
            "  - id: idx",
            "    type: s4",
            "  - id: prev_interm_value",
            "    type: u8",
            "  - id: multiplier",
            "    type: u8",
            "seq:",
            "  - id: has_next",
            "    type: b1",
            '    valid: "idx == 9 ? false : has_next"',
            "  - id: value",
            "    type: b7",
            "    valid:",
            '      max: "(idx == 9 ? 1 : 127).as<u8>"',
            "instances:",
            "  interm_value:",
            "    value: (prev_interm_value + value * multiplier).as<u8>",
        ])
        for item in self.items:
            for member in item.fields:
                kind = member.encoding.get("kind", "").lower()
                if kind == "message":
                    target = _find_item(
                        self.items, member.type_name or member.encoding.get("source_type", ""),
                        item)
                    root_is_referenced |= target is self.root
                elif kind == "map":
                    value_type = member.mapping.get("value_type")
                    value_kind = member.mapping.get("value_kind")
                    if value_type and self._map_value_kind(
                            value_type, value_kind)[0] == "message":
                        root_is_referenced |= _find_item(self.items, value_type, item) is self.root
        if root_is_referenced:
            self.root.message_type_id = _identifier(f"{self.root.ksy_id}__body")
        for item in self.items:
            if item.layout != "protobuf":
                continue
            cases = {}
            for member in item.fields:
                if not member.encoding:
                    raise KaitaiError(
                        f"{item.name}.{member.name}: Protobuf field is missing DataEncoding")
                try:
                    number = int(member.encoding["field_number"])
                    kind = member.encoding["kind"].lower()
                    wire_type = int(member.encoding["wire_type"])
                    source_type = member.encoding["source_type"]
                except (KeyError, ValueError):
                    raise KaitaiError(
                        f"{item.name}.{member.name}: incomplete DataEncoding metadata") from None
                if number <= 0:
                    raise KaitaiError(
                        f"{item.name}.{member.name}: Protobuf field number must be positive")
                if kind == "group":
                    raise KaitaiError(
                        f"{item.name}.{member.name}: Protobuf groups are not supported")
                base_wire = {
                    "varint": 0, "zigzag": 0, "enum": 0, "fixed64": 1,
                    "string": 2, "bytes": 2, "message": 2, "map": 2,
                    "fixed32": 5,
                }.get(kind)
                if base_wire is None:
                    raise KaitaiError(
                        f"{item.name}.{member.name}: unsupported DataEncoding kind {kind!r}")
                repeated = member.upper is None
                allowed = {base_wire}
                if repeated and kind in (
                        "varint", "zigzag", "enum", "fixed32", "fixed64"):
                    allowed.add(2)
                if wire_type not in allowed:
                    raise KaitaiError(
                        f"{item.name}.{member.name}: wire type {wire_type} conflicts with {kind}")
                target = self._find_message(member.type_name or source_type, item) \
                    if kind == "message" else None
                if kind == "map":
                    target = self._map_type(item, member)
                cases[number * 8 + base_wire] = self._payload(
                    item, member, "value", source_type, kind, target)
                if repeated and kind in (
                        "varint", "zigzag", "enum", "fixed32", "fixed64"):
                    cases[number * 8 + 2] = self._packed_payload(
                        item.ksy_id + "_" + member.ksy_id, "packed",
                        source_type, kind)
            field_type = _identifier(f"_pb_{item.ksy_id}_field")
            self.message_bodies[item] = [
                "seq:",
                "  - id: fields",
                f"    type: {field_type}",
                "    repeat: eos",
            ]
            self._register(field_type, self._field_parser_body(cases))
        unknown_bytes = self._register(
            _PROTO_BYTES,
            ["seq:", "  - id: length", f"    type: {_PROTO_VARINT}",
             "  - id: value", "    size: length.value"])
        self._register(
            _PROTO_UNKNOWN,
            ["params:", "  - id: wire_type", "    type: u1",
             "seq:", "  - id: value", "    type:",
             "      switch-on: wire_type", "      cases:",
             f"        0: {_PROTO_VARINT}", "        1: u8",
             f"        2: {unknown_bytes}", "        5: u4"])
        return self.message_bodies, self.helpers


@dataclass
class _HelperType:
    ksy_id: str


def _render_types(root, items, helpers, protobuf_bodies=None,
                  integer_signedness=False):
    types = []
    for item in items:
        if item is root:
            if item.message_type_id is not None:
                types.append((item.message_type_id, protobuf_bodies[item]))
            continue
        if item.layout == "protobuf":
            body = protobuf_bodies[item]
        else:
            sequence = _seq_lines(item, items, integer_signedness)
            if not sequence:
                raise KaitaiError(f"{item.name}: item has no fields to generate")
            body = ["seq:", *sequence]
            if item.signed_instances:
                body.append("instances:")
                for name, expression in item.signed_instances:
                    body.extend((f"  {name}:", f'    value: "{expression}"'))
        types.append((item.ksy_id, body))
    if helpers:
        types.extend(helpers.items())
    if not types:
        return []
    names = [name for name, _ in types]
    if len(names) != len(set(names)):
        raise KaitaiError("generated Kaitai type names collide")
    lines = ["types:"]
    for name, body in types:
        lines.append(f"  {name}:")
        lines.extend(f"    {line}" for line in body)
    return lines


def _render_seq(item, items, integer_signedness):
    sequence = _seq_lines(item, items, integer_signedness)
    if not sequence:
        raise KaitaiError(f"{item.name}: item has no fields to generate")
    result = ["seq:", *sequence]
    if item.signed_instances:
        result.append("instances:")
        for name, expression in item.signed_instances:
            result.extend((f"  {name}:", f'    value: "{expression}"'))
    return result


def _root_item(text, name):
    tree = sysml.parse(text)
    contexts = list(sysml.find_all(tree, P.ItemDefinitionContext))
    if name is not None:
        matches = [
            context for context in contexts
            if _unquote(sysml.decl_name(
                sysml.find_first(context, P.DefinitionDeclarationContext))) == _unquote(name)
        ]
        if not matches:
            raise KaitaiError(f"no item definition named {name!r} found")
        if len(matches) > 1:
            raise KaitaiError(f"item definition {name!r} is ambiguous")
        return tree, _item_from_context(matches[0])
    top = _message_contexts(tree)
    if len(top) != 1:
        raise KaitaiError(
            "select one top-level item with --item; "
            f"found {len(top)} top-level item definitions")
    return tree, _item_from_context(top[0])


def generate(text, item=None, endian="le", bit_endian="le",
             integer_signedness="unsigned"):
    """Return KSY YAML for one SysML item definition."""
    if endian not in ("le", "be") or bit_endian not in ("le", "be"):
        raise KaitaiError("endian and bit_endian must be 'le' or 'be'")
    if integer_signedness not in ("signed", "unsigned"):
        raise KaitaiError("integer_signedness must be 'signed' or 'unsigned'")
    _, root = _root_item(text, item)
    _assign_ids(root)
    items = list(_all_items(root))
    if root.layout == "protobuf":
        if endian != "le":
            raise KaitaiError("Protobuf fixed-width values are always little-endian")
        builder = _ProtoBuilder(root, items)
        message_bodies, helpers = builder.build()
        if root not in message_bodies:
            raise KaitaiError(f"{root.name}: Protobuf fields have no wire metadata")
        if root.message_type_id is not None:
            sequence = ["seq:", "  - id: message",
                        f"    type: {root.message_type_id}"]
        else:
            sequence = message_bodies[root]
        type_lines = _render_types(root, items, helpers, message_bodies)
        encoding = "UTF-8"
    else:
        if any(entry.layout == "protobuf" for entry in items):
            raise KaitaiError("Protobuf message types must be generated as the root item")
        sequence = _render_seq(root, items, integer_signedness == "signed")
        type_lines = _render_types(
            root, items, {}, integer_signedness == "signed")
        encoding = "UTF-8"
    lines = [
        "meta:",
        f"  id: {root.ksy_id}",
        f"  endian: {endian}",
        f"  bit-endian: {'be' if root.layout == 'protobuf' else bit_endian}",
        f"  encoding: {encoding}",
        *sequence,
        *type_lines,
    ]
    return "\n".join(lines) + "\n"
