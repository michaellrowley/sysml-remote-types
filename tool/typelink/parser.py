"""Extracts and validates @TypeLink annotations from SysMLv2 text."""
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from . import spec

_DEF = re.compile(r"\b(\w+)\s+def\s+(\w+)\s*\{")
_LINK = re.compile(r"@TypeLink\s*\{(.*?)\}", re.S)
_ASSIGN = re.compile(r'(\w+)\s*=\s*(?:(\w+)::(\w+)|"([^"]*)")\s*;')


@dataclass
class Link:
    element: str
    origin: str
    uri: str


class TypeLinkError(ValueError):
    pass


def parse(text):
    origins, attrs = spec.load()
    links = []
    for m in _LINK.finditer(text):
        owner = [d for d in _DEF.finditer(text, 0, m.start())]
        name = owner[-1].group(2) if owner else "<unknown>"
        values = {}
        for key, enum_t, enum_v, string in _ASSIGN.findall(m.group(1)):
            if key not in attrs:
                raise TypeLinkError(f"{name}: unknown attribute '{key}'")
            if key in values:
                raise TypeLinkError(f"{name}: duplicate attribute '{key}'")
            if attrs[key] == "String":
                if enum_t:
                    raise TypeLinkError(f"{name}: '{key}' must be a string")
                values[key] = string
            else:
                if enum_t != attrs[key] or enum_v not in origins:
                    raise TypeLinkError(
                        f"{name}: '{key}' must be one of "
                        + ", ".join(f"{attrs[key]}::{o}" for o in origins))
                values[key] = enum_v
        for key in attrs:
            if key not in values:
                raise TypeLinkError(f"{name}: missing attribute '{key}'")
        u = urlparse(values["uri"])
        if not (u.scheme and (u.netloc or u.path)):
            raise TypeLinkError(f"{name}: 'uri' must be an absolute URI")
        links.append(Link(name, values["origin"], values["uri"]))
    return links
