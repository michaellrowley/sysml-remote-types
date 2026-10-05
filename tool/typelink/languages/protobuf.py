"""Protocol Buffers message importer built on proto-schema-parser."""
from proto_schema_parser import Parser
from proto_schema_parser import ast
from proto_schema_parser.ast import FieldCardinality

from .. import spec as specmod
from ..model import ImportError_, Member, Result, Struct
from . import Importer, register


def _import_proto(source, element):
    scalars = specmod.load_types()["protobuf_scalars"]
    f = Parser().parse(source)
    messages, enums = {}, set()

    def collect(elements):
        for e in elements:
            if isinstance(e, ast.Message):
                messages.setdefault(e.name, e)
                collect(e.elements)
            elif isinstance(e, ast.Enum):
                enums.add(e.name)

    collect(f.file_elements)
    if element not in messages:
        raise ImportError_(f"no message named '{element}' found")
    warnings, cache = [], {}

    def fields(elems):
        for e in elems:
            if isinstance(e, ast.Field):
                yield e, e.cardinality
            elif isinstance(e, ast.Group):
                warnings.append(f"group '{e.name}' is not supported")
            elif isinstance(e, ast.OneOf):
                for o in e.elements:
                    if isinstance(o, ast.Field):
                        yield o, FieldCardinality.OPTIONAL
            elif isinstance(e, ast.MapField):
                yield e, None

    def build(name):
        if name in cache:
            return cache[name]
        st = Struct(name)
        cache[name] = st            # total size stays None: wire size is variable
        for fld, card in fields(messages[name].elements):
            if isinstance(fld, ast.MapField):
                m = Member(fld.name, "unresolved", None, f"map<{fld.key_type}, {fld.value_type}>", 0, None)
                warnings.append(f"{name}.{fld.name}: map fields are variable-length")
            else:
                t = fld.type.split(".")[-1]
                if fld.type in scalars:
                    kind, bits = scalars[fld.type]
                    m = Member(fld.name, kind, bits)
                elif t in enums:
                    m = Member(fld.name, "integer", 32)
                elif t in messages:
                    sub = build(t)
                    if sub not in st.nested:
                        st.nested.append(sub)
                    m = Member(fld.name, "struct", None, sub.name)
                else:
                    warnings.append(f"{name}.{fld.name}: unresolved type '{fld.type}'")
                    m = Member(fld.name, "unresolved", None, fld.type)
                if card == FieldCardinality.REPEATED:
                    m.lower, m.upper = 0, None
                elif card == FieldCardinality.OPTIONAL:
                    m.lower, m.upper = 0, 1
            st.members.append(m)
        return st

    return Result(build(element), warnings)


@register("Protobuf")
class ProtobufImporter(Importer):
    def import_type(self, source, element, data_model=None):
        return _import_proto(source, element)
