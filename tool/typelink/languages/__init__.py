"""Language importers, keyed by the TypeOrigin enum literal in spec/typelink.sysml.

To add a language (e.g. Rust):
  1. add an `enum` literal to TypeOrigin in spec/typelink.sysml (then `sync-spec`);
  2. add its grammar as a pinned submodule under third_party/ (if using tree-sitter,
     call `typelink.treesitter.get_language`) and list it in the RFC/README;
  3. add a module here with a class decorated by `@register("Rust")` implementing
     `Importer.import_type`, and import it at the bottom of this file;
  4. add any scalar widths to spec/types.json.
The tests fail if a TypeOrigin literal has no registered importer.
"""
from ..model import ImportError_, Result

_REGISTRY = {}


class Importer:
    """Turns source text in some language into a language-neutral `Result`."""

    def import_type(self, source, element, data_model=None):
        raise NotImplementedError


def register(origin):
    def deco(cls):
        _REGISTRY[origin] = cls
        return cls
    return deco


def get(origin):
    try:
        return _REGISTRY[origin]()
    except KeyError:
        raise ImportError_(f"no importer for origin {origin}") from None


def origins():
    return sorted(_REGISTRY)


from . import c, protobuf  # noqa: E402,F401  (registers importers)
