"""Language-neutral source-header generation and backend registry."""
from importlib import import_module

from .. import kaitai as kaitai_generator
from .kaitai import _records, apply as apply_kaitai, item_selectors
from .sysml import HeaderError, resolve

_BACKENDS = {"c": "c", "cpp": "cpp", "rust": "rust"}


def languages():
    """Return names of supported header backends."""
    return sorted(_BACKENDS)


def generate_schemas(text):
    """Generate a KSY document for each non-empty top-level item."""
    module = resolve(text)
    records = dict(_records(module.root))
    schemas = []
    for selector in item_selectors(text):
        record = records.get(tuple(selector.split("::")))
        if (record is not None and not record.fields and not record.nested
                and not record.bases and not record.bits):
            continue
        schemas.append((
            selector, kaitai_generator.generate(text, item=f"::{selector}")))
    return schemas


def generate(text, language="cpp", schemas=None, declarations_only=False):
    """Resolve SysML declarations, source record fields from KSY, and render."""
    backend = _BACKENDS.get(language)
    if backend is None:
        raise HeaderError(
            f"unsupported header language {language!r}; supported: {', '.join(languages())}")
    if schemas is None:
        schemas = generate_schemas(text)
    module = resolve(text)
    apply_kaitai(module, schemas)
    renderer = import_module(f"{__name__}.{backend}")
    return renderer.render(module, declarations_only=declarations_only)
