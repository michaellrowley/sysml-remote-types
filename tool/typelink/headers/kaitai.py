"""Build header record members from generated Kaitai Struct schemas."""
import re

import yaml

from .. import sysml
from .model import Field, Record
from .sysml import HeaderError, _unquote

P = sysml.P
_PRIMITIVE_BITS = {
    "u1": 8, "s1": 8, "u2": 16, "s2": 16,
    "u4": 32, "s4": 32, "u8": 64, "s8": 64,
    "f4": 32, "f8": 64,
}


def _identifier(value):
    result = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if result and result[0].isdigit():
        result = "t_" + result
    return result


def item_selectors(text):
    """Return qualified names of top-level item definitions in source order."""
    tree = sysml.parse(text)
    selectors = []
    for context in sysml.find_all(tree, P.ItemDefinitionContext):
        if sysml.ancestor(context.parentCtx, P.ItemDefinitionContext) is not None:
            continue
        declaration = sysml.find_first(context, P.DefinitionDeclarationContext)
        packages = []
        parent = context.parentCtx
        while parent is not None:
            if isinstance(parent, P.PackageContext):
                package = parent.packageDeclaration()
                if package is not None and package.identification() is not None:
                    packages.append(_unquote(sysml.decl_name(package)))
            parent = parent.parentCtx
        selectors.append("::".join(
            list(reversed(packages)) + [_unquote(sysml.decl_name(declaration))]))
    return selectors


def _records(namespace, path=()):
    current = path + ((_unquote(namespace.name),) if namespace.name else ())
    for record in namespace.records:
        yield current + (record.name,), record
        yield from _nested_records(record, current + (record.name,))
    for child in namespace.namespaces:
        yield from _records(child, current)


def _nested_records(record, path):
    for child in record.nested:
        child_path = path + (child.name,)
        yield child_path, child
        yield from _nested_records(child, child_path)


def _plain_type(value):
    if not isinstance(value, str):
        return None
    value = value.strip().strip("'\"")
    return value.split("(", 1)[0].strip()


def _repeat_bounds(entry):
    repeat = entry.get("repeat")
    if repeat is None:
        return 1, 1
    if repeat == "expr":
        expression = entry.get("repeat-expr")
        try:
            count = int(expression)
        except (TypeError, ValueError):
            return 0, None
        if count < 0:
            raise HeaderError(f"invalid Kaitai repeat count {expression!r}")
        return count, count
    if repeat == "until":
        return 1, None
    if repeat == "eos":
        return 0, None
    raise HeaderError(f"unsupported Kaitai repeat mode {repeat!r}")


def _type_alternatives(type_value):
    if not isinstance(type_value, dict):
        return []
    cases = type_value.get("cases", {})
    if not isinstance(cases, dict):
        raise HeaderError("unsupported Kaitai switch cases")
    if not cases:
        raise HeaderError("Kaitai switch type has no cases")
    alternatives = []
    for case in cases.values():
        type_name = _plain_type(case)
        if type_name and type_name not in alternatives:
            alternatives.append(type_name)
    if not alternatives:
        raise HeaderError("Kaitai switch type has no supported case types")
    return alternatives


def _base_size(type_value, types, stack):
    type_name = _plain_type(type_value)
    if type_name is None:
        alternatives = _type_alternatives(type_value)
        sizes = [_base_size(value, types, stack) for value in alternatives]
        return sizes[0] if sizes and all(size == sizes[0] for size in sizes) else None
    if type_name in _PRIMITIVE_BITS:
        return _PRIMITIVE_BITS[type_name]
    match = re.fullmatch(r"b([1-9][0-9]*)", type_name)
    if match:
        width = int(match.group(1))
        if width > 64:
            raise HeaderError(f"Kaitai bit field width {width} exceeds 64 bits")
        return width
    if type_name == "str":
        return None
    if type_name in types:
        if type_name in stack:
            return None
        body = types[type_name]
        sequence = body.get("seq", []) if isinstance(body, dict) else []
        total = 0
        for entry in sequence:
            _, bits, lower, upper, _ = _entry_shape(
                entry, types, (*stack, type_name))
            if bits is None or upper is None or lower != upper:
                return None
            total += bits * upper
        return total
    return None


def _entry_shape(entry, types, stack=()):
    if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
        raise HeaderError("invalid Kaitai sequence entry")
    type_value = entry.get("type")
    type_name = _plain_type(type_value)
    alternatives = _type_alternatives(type_value)
    size = entry.get("size")
    if isinstance(size, bool) or (isinstance(size, int) and size < 0):
        raise HeaderError(
            "Kaitai field size must be a non-negative integer or expression")
    if type_value is not None and type_name is None and not alternatives:
        raise HeaderError("unsupported Kaitai field type shape")
    if type_name is None and not alternatives:
        if isinstance(size, int):
            type_name = "u1"
            lower = upper = size
            return type_name, 8, lower, upper, alternatives
        if size is not None:
            return "u1", 8, 0, None, alternatives
        type_name = "u1"
    lower, upper = _repeat_bounds(entry)
    if "if" in entry:
        lower, upper = 0, 1
    if isinstance(size, int) and size >= 0:
        bits = (size * 8 if type_name in ("str", "u1")
                else _base_size(type_value, types, stack))
    elif type_name == "str":
        bits = None
    else:
        bits = _base_size(type_value, types, stack)
    return type_name or "choice", bits, lower, upper, alternatives


def _schema_fields(sequence, types, type_names, excluded=()):
    fields = []
    cursor = 0
    excluded = set(excluded)
    for entry in sequence:
        type_name, bits, lower, upper, alternatives = _entry_shape(entry, types)
        identifier = entry["id"]
        field = Field(
            name=identifier,
            type_name=type_names.get(type_name, type_name),
            lower=lower,
            upper=upper,
            bits=bits,
            offset_bits=cursor if cursor is not None else None,
            alternatives=[type_names.get(value, value) for value in alternatives],
        )
        if identifier not in excluded:
            fields.append(field)
        if cursor is not None:
            if bits is None or upper is None or lower != upper:
                cursor = None
            else:
                cursor += bits * upper
    return fields, cursor


def _helper_name(type_id):
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", type_id) if part]
    name = "Kaitai" + "".join(part[:1].upper() + part[1:] for part in parts)
    return name if name != "Kaitai" else "KaitaiType"


def _qualified_path(name, namespace_path, records):
    parts = tuple(name.split("::"))
    if name.startswith("::"):
        parts = tuple(name[2:].split("::"))
        return parts if parts in records else None
    for candidate in (namespace_path + parts, parts):
        if candidate in records:
            return candidate
    return None


def _record_for_selector(module_records, selector):
    path = tuple(selector.split("::"))
    record = module_records.get(path)
    if record is None:
        raise HeaderError(
            f"Kaitai schema item {selector!r} has no SysML item definition")
    return path, record


def apply(module, schemas):
    """Replace structural fields with those described by generated KSY documents."""
    module_records = dict(_records(module.root))
    for record in module_records.values():
        record.fields = []
        record.bits = None
    roots = {}
    documents = {}
    for selector, source in schemas:
        try:
            document = yaml.safe_load(source)
        except yaml.YAMLError as error:
            raise HeaderError(
                f"invalid generated Kaitai schema for {selector}: {error}") from error
        if not isinstance(document, dict) or not isinstance(document.get("meta"), dict):
            raise HeaderError(
                f"generated Kaitai schema for {selector} has no meta block")
        path, record = _record_for_selector(module_records, selector)
        roots[selector] = (path, record)
        documents[selector] = document

    selector_for_path = {path: selector for selector, (path, _) in roots.items()}
    for selector, (path, record) in roots.items():
        document = documents[selector]
        sequence = document.get("seq")
        if not isinstance(sequence, list):
            raise HeaderError(f"generated Kaitai schema for {selector} has no sequence")
        types = document.get("types", {})
        if not isinstance(types, dict):
            raise HeaderError(
                f"generated Kaitai schema for {selector} has invalid types")
        type_records = {}
        type_names = {}

        def nested_aliases(root_record):
            aliases = {}

            def visit(item, nested_path=()):
                for child in item.nested:
                    child_path = nested_path + (child.name,)
                    alias = _identifier("__".join((root_record.name, *child_path)))
                    aliases[alias] = child
                    visit(child, child_path)

            visit(root_record)
            return aliases

        aliases = nested_aliases(record)
        for type_id in types:
            nested = aliases.get(_identifier(type_id))
            helper = nested or Record(_helper_name(type_id))
            type_records[type_id] = helper
            type_names[type_id] = helper.name

        for type_id, type_record in type_records.items():
            type_body = types[type_id]
            if not isinstance(type_body, dict):
                raise HeaderError(f"Kaitai type {type_id!r} must be a mapping")
            type_sequence = type_body.get("seq", [])
            if not isinstance(type_sequence, list):
                raise HeaderError(f"Kaitai type {type_id!r} has an invalid sequence")
            type_record.fields, type_record.bits = _schema_fields(
                type_sequence, types, type_names)
            type_record.nested = []
        record.nested = list(type_records.values())

        excluded = set()
        namespace_path = path[:-1]
        for base in record.bases:
            base_path = _qualified_path(base, namespace_path, module_records)
            base_selector = selector_for_path.get(base_path)
            if base_selector is not None:
                base_sequence = documents[base_selector].get("seq", [])
                excluded.update(
                    entry["id"] for entry in base_sequence
                    if isinstance(entry, dict) and isinstance(entry.get("id"), str))
        record.fields, record.bits = _schema_fields(
            sequence, types, type_names, excluded=excluded)
