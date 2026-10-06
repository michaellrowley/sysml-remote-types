"""Protocol Buffers message importer built on proto-schema-parser."""
from proto_schema_parser import Parser
from proto_schema_parser import ast
from proto_schema_parser.ast import FieldCardinality

from .. import spec as specmod
from ..model import ImportError_, Member, Result, Struct, WireField
from . import Importer, register


_WIRE_TYPES = {
    "int32": ("varint", 0), "int64": ("varint", 0),
    "uint32": ("varint", 0), "uint64": ("varint", 0),
    "bool": ("varint", 0), "sint32": ("zigzag", 0), "sint64": ("zigzag", 0),
    "fixed32": ("fixed32", 5), "sfixed32": ("fixed32", 5), "float": ("fixed32", 5),
    "fixed64": ("fixed64", 1), "sfixed64": ("fixed64", 1), "double": ("fixed64", 1),
    "string": ("string", 2), "bytes": ("bytes", 2),
}


def _import_proto(source, element, additional_sources=()):
    scalars = specmod.load_types()["protobuf_scalars"]
    files = [Parser().parse(text) for text in (source, *additional_sources)]
    messages, message_syntax, enums = {}, {}, set()

    def collect(elements, syntax):
        for e in elements:
            if isinstance(e, ast.Message):
                messages.setdefault(e.name, e)
                message_syntax.setdefault(e.name, syntax)
                collect(e.elements, syntax)
            elif isinstance(e, ast.Enum):
                enums.add(e.name)

    for f in files:
        collect(f.file_elements, f.syntax)
    if element not in messages:
        raise ImportError_(f"no message named '{element}' found")
    warnings, cache = [], {}

    def fields(elems):
        for e in elems:
            if isinstance(e, ast.Field):
                yield e, e.cardinality
            elif isinstance(e, ast.Group):
                warnings.append(f"group '{e.name}' is not supported")
                yield e, e.cardinality
            elif isinstance(e, ast.OneOf):
                for o in e.elements:
                    if isinstance(o, ast.Field):
                        yield o, FieldCardinality.OPTIONAL
            elif isinstance(e, ast.MapField):
                yield e, None

    def wire_field(fld, card, message_name):
        if isinstance(fld, ast.MapField):
            value_name = fld.value_type.split(".")[-1]
            if value_name in _WIRE_TYPES:
                value_kind = "scalar"
            elif value_name in enums:
                value_kind = "enum"
            elif value_name in messages:
                value_kind = "message"
            else:
                value_kind = "unresolved"
            return WireField(fld.number, "map", "map", 2,
                             key_type=fld.key_type, value_type=fld.value_type,
                             value_kind=value_kind)
        if isinstance(fld, ast.Group):
            return WireField(fld.number, "group", fld.name, 3)
        source_type = fld.type
        short_type = source_type.split(".")[-1]
        if short_type in _WIRE_TYPES:
            kind, wire_type = _WIRE_TYPES[short_type]
        elif short_type in enums:
            kind, wire_type = "enum", 0
        elif short_type in messages:
            kind, wire_type = "message", 2
        else:
            kind, wire_type = "unresolved", 0
        packable = kind in ("varint", "zigzag", "fixed32", "fixed64", "enum")
        packed_option = next(
            (option.value for option in getattr(fld, "options", ())
             if option.name == "packed"), None)
        packed = bool(packed_option) if packed_option is not None else (
            packable and card == FieldCardinality.REPEATED
            and message_syntax.get(message_name) == "proto3")
        declared_wire_type = (
            2 if packable and card == FieldCardinality.REPEATED and packed
            else wire_type)
        return WireField(fld.number, kind, source_type, declared_wire_type,
                         packed=packed)

    def build(name):
        if name in cache:
            return cache[name]
        st = Struct(name, layout_kind="protobuf")
        cache[name] = st            # total size stays None: wire size is variable
        for fld, card in fields(messages[name].elements):
            wire = wire_field(fld, card, name)
            if isinstance(fld, ast.MapField):
                m = Member(fld.name, "unresolved", None,
                           f"map<{fld.key_type}, {fld.value_type}>", 0, None,
                           wire=wire)
                value_name = fld.value_type.split(".")[-1]
                if value_name in messages:
                    sub = build(value_name)
                    if sub is not st and sub not in st.nested:
                        st.nested.append(sub)
                warnings.append(f"{name}.{fld.name}: map fields are variable-length")
            elif isinstance(fld, ast.Group):
                m = Member(fld.name, "unresolved", None, fld.name, wire=wire)
            else:
                t = fld.type.split(".")[-1]
                if fld.type in scalars:
                    kind, bits = scalars[fld.type]
                    m = Member(fld.name, kind, bits, wire=wire)
                elif t in enums:
                    m = Member(fld.name, "integer", 32, wire=wire)
                elif t in messages:
                    sub = build(t)
                    if sub is not st and sub not in st.nested:
                        st.nested.append(sub)
                    m = Member(fld.name, "struct", None, sub.name, wire=wire)
                else:
                    warnings.append(f"{name}.{fld.name}: unresolved type '{fld.type}'")
                    m = Member(fld.name, "unresolved", None, fld.type, wire=wire)
                if card == FieldCardinality.REPEATED:
                    m.lower, m.upper = 0, None
                elif card == FieldCardinality.OPTIONAL:
                    m.lower, m.upper = 0, 1
            st.members.append(m)
        return st

    return Result(build(element), warnings)


@register("Protobuf")
class ProtobufImporter(Importer):
    def import_type(self, source, element, data_model=None, additional_sources=()):
        return _import_proto(source, element, additional_sources)
