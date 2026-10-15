"""Resolve SysML structural and behavioral declarations into the header IR."""
import re

from .. import sysml
from .model import Field, Function, Module, Namespace, Record

P = sysml.P


class HeaderError(ValueError):
    """A SysML declaration cannot be represented by the header generator."""


def _unquote(value):
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("\\'", "'")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _declaration_name(context):
    name = sysml.decl_name(context)
    if not name:
        raise HeaderError("declaration has no name")
    return _unquote(name)


def _metadata_values(feature):
    values = {}
    for assignment in sysml.find_all(feature, P.MetadataBodyFeatureContext):
        key = assignment.ownedRedefinition().getText()
        value = sysml.find_first(assignment, P.ValuePartContext)
        if value is None:
            continue
        raw = value.getText().lstrip("=")
        values[key] = _unquote(raw)
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
        raise HeaderError(f"duplicate @{name} annotation")
    return matches[0] if matches else {}


def _natural(values, key):
    raw = values.get(key)
    if raw is None:
        return None
    try:
        result = int(raw)
    except ValueError:
        raise HeaderError(f"@{key} must be a non-negative integer") from None
    if result < 0:
        raise HeaderError(f"@{key} must be a non-negative integer")
    return result


def _multiplicity(declaration):
    ranges = list(sysml.find_all(declaration, P.OwnedMultiplicityRangeContext))
    if len(ranges) > 1:
        raise HeaderError("multi-dimensional multiplicity is not supported")
    if not ranges:
        return 1, 1
    raw = ranges[0].getText()
    if not (raw.startswith("[") and raw.endswith("]")):
        raise HeaderError(f"invalid multiplicity {raw!r}")
    raw = raw[1:-1]
    if ".." not in raw:
        try:
            count = int(raw)
        except ValueError:
            raise HeaderError(f"unsupported multiplicity [{raw}]") from None
        if count < 0:
            raise HeaderError(f"unsupported multiplicity [{raw}]")
        return count, count
    lower_raw, upper_raw = raw.split("..", 1)
    try:
        lower = int(lower_raw)
        upper = None if upper_raw == "*" else int(upper_raw)
    except ValueError:
        raise HeaderError(f"unsupported multiplicity [{raw}]") from None
    if lower < 0 or (upper is not None and upper < lower):
        raise HeaderError(f"unsupported multiplicity [{raw}]")
    return lower, upper


def _namespace_path(context):
    packages = []
    parent = context.parentCtx
    while parent is not None:
        if isinstance(parent, P.PackageContext):
            declaration = parent.packageDeclaration()
            if declaration is not None and declaration.identification() is not None:
                packages.append(_declaration_name(declaration))
        parent = parent.parentCtx
    return list(reversed(packages))


def _get_namespace(root, path):
    current = root
    for name in path:
        child = next((entry for entry in current.namespaces if entry.name == name), None)
        if child is None:
            child = Namespace(name)
            current.namespaces.append(child)
        current = child
    return current


def _field_from_usage(usage, direction="in"):
    declaration = usage.usageDeclaration()
    if declaration is None:
        raise HeaderError(f"unsupported feature usage {usage.getText()!r}")
    wrapper = sysml.ancestor(usage, (P.ItemUsageContext, P.AttributeUsageContext))
    if wrapper is None:
        return None
    typing = sysml.find_first(declaration, P.OwnedFeatureTypingContext)
    if typing is None:
        raise HeaderError(f"{declaration.getText()}: a data type is required")
    name_context = sysml.find_first(declaration, P.IdentificationContext)
    if name_context is None:
        raise HeaderError(f"cannot read feature name from {declaration.getText()!r}")
    scope = sysml.find_first(usage, P.DefinitionBodyContext)
    size = _metadata(scope, "DataSize")
    offset = _metadata(scope, "DataOffset")
    lower, upper = _multiplicity(declaration)
    return Field(
        name=_unquote(name_context.getText()),
        type_name=typing.getText(),
        lower=lower,
        upper=upper,
        direction=direction,
        bits=_natural(size, "bits"),
        offset_bits=_natural(offset, "bits"),
    )


def _record(context):
    declaration = sysml.find_first(context, P.DefinitionDeclarationContext)
    if declaration is None:
        raise HeaderError("item definition has no declaration")
    record = Record(name=_declaration_name(declaration))
    subclassification = declaration.subclassificationPart()
    if subclassification is not None:
        record.bases = [
            _unquote(base.qualifiedName().getText())
            for base in subclassification.ownedSubclassification()
        ]
    body = sysml.find_first(context, P.DefinitionBodyContext)
    record.bits = _natural(_metadata(body, "DataSize"), "bits")
    if body is None:
        return record

    for child in sysml.find_all(body, P.ItemDefinitionContext):
        if sysml.ancestor(child, P.DefinitionBodyContext) is body:
            record.nested.append(_record(child))
    for usage in sysml.find_all(body, P.UsageContext):
        if sysml.ancestor(usage, P.DefinitionBodyContext) is not body:
            continue
        field = _field_from_usage(usage)
        if field is not None:
            record.fields.append(field)
    return record


def _action(context, source):
    declaration = context.definitionDeclaration()
    function = Function(name=_declaration_name(declaration))
    body = context.actionBody()
    if body is None:
        return function

    for usage in sysml.find_all(body, P.UsageContext):
        if sysml.ancestor(usage, P.ActionDefinitionContext) is not context:
            continue
        action_body_item = sysml.ancestor(usage, P.ActionBodyItemContext)
        if action_body_item is None or action_body_item.parentCtx is not body:
            continue
        wrapper = sysml.ancestor(usage, (P.ItemUsageContext, P.AttributeUsageContext))
        prefix = sysml.find_first(wrapper, P.FeatureDirectionContext)
        direction = prefix.getText() if prefix is not None else "in"
        parameter = _field_from_usage(usage, direction)
        if parameter is not None:
            function.parameters.append(parameter)

    connection_types = (
        P.InitialNodeMemberContext,
        P.ActionTargetSuccessionMemberContext,
        P.SourceSuccessionMemberContext,
        P.GuardedSuccessionMemberContext,
    )
    connections = []
    for node in sysml.walk(body):
        if not isinstance(node, connection_types):
            continue
        if sysml.ancestor(node, P.ActionDefinitionContext) is not context:
            continue
        text = re.sub(r"\s+", " ", sysml.source_text(source, node)).strip()
        if text and text not in connections:
            connections.append(text)
    function.connections = connections
    return function


def resolve(text):
    """Parse one SysML document into a language-neutral header module."""
    tree = sysml.parse(text)
    module = Module()
    for context in sysml.find_all(tree, P.ItemDefinitionContext):
        if sysml.ancestor(context.parentCtx, P.ItemDefinitionContext) is not None:
            continue
        _get_namespace(module.root, _namespace_path(context)).records.append(
            _record(context))
    for context in sysml.find_all(tree, P.ActionDefinitionContext):
        if sysml.ancestor(context.parentCtx, P.ActionDefinitionContext) is not None:
            continue
        _get_namespace(module.root, _namespace_path(context)).functions.append(
            _action(context, text))
    return module
