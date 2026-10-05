"""Extracts and validates @TypeLink annotations using the SysMLv2 parse tree."""
from dataclasses import dataclass
from urllib.parse import urlparse

from . import spec as specmod
from . import sysml

P = sysml.P


@dataclass
class Link:
    element: str
    origin: str
    uri: str
    definition: object = None   # DefinitionBody context holding the annotation (None in JSON)
    link_ctx: object = None


class TypeLinkError(ValueError):
    pass


def _value(feature):
    """Returns ('enum', 'Type', 'Literal') or ('string', value) for an assignment."""
    expr = sysml.find_first(feature, P.ValuePartContext)
    if expr is None:
        return None
    lit = sysml.find_first(expr, P.LiteralStringContext)
    if lit is not None:
        raw = lit.getText()
        return ("string", raw[1:-1])
    q = sysml.find_first(expr, P.QualifiedNameContext)
    if q is not None:
        parts = [n.getText() for n in sysml.find_all(q, P.NameContext)]
        return ("enum", "::".join(parts[:-1]), parts[-1])
    return None


def extract(tree, spec=None):
    spec = spec or specmod.load()
    attrs = spec.link_attrs
    links = []
    for mf in sysml.find_all(tree, P.MetadataFeatureContext):
        typing = sysml.find_first(mf.metadataFeatureDeclaration(), P.OwnedFeatureTypingContext)
        if typing is None or typing.getText() != "TypeLink":
            continue
        owner = sysml.ancestor(mf, P.DefinitionContext)
        name = sysml.decl_name(owner.definitionDeclaration()) if owner else "<unknown>"
        values = {}
        for feat in sysml.find_all(mf, P.MetadataBodyFeatureContext):
            key = feat.ownedRedefinition().getText()
            if key not in attrs:
                raise TypeLinkError(f"{name}: unknown attribute '{key}'")
            if key in values:
                raise TypeLinkError(f"{name}: duplicate attribute '{key}'")
            val = _value(feat)
            if val is None:
                raise TypeLinkError(f"{name}: '{key}' needs a literal value")
            if attrs[key] == "String":
                if val[0] != "string":
                    raise TypeLinkError(f"{name}: '{key}' must be a string")
                values[key] = val[1]
            else:
                if val[0] != "enum" or val[1] != attrs[key] or val[2] not in spec.origins:
                    raise TypeLinkError(
                        f"{name}: '{key}' must be one of "
                        + ", ".join(f"{attrs[key]}::{o}" for o in spec.origins))
                values[key] = val[2]
        for key in attrs:
            if key not in values:
                raise TypeLinkError(f"{name}: missing attribute '{key}'")
        u = urlparse(values["uri"])
        if not (u.scheme and (u.netloc or u.path)):
            raise TypeLinkError(f"{name}: 'uri' must be an absolute URI")
        links.append(Link(name, values["origin"], values["uri"],
                          owner.definitionBody() if owner else None, mf))
    return links


def parse(text):
    return extract(sysml.parse(text))
