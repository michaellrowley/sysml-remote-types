"""Language-neutral source-header generation and backend registry."""
from importlib import import_module

from .sysml import HeaderError, resolve

_BACKENDS = {"cpp": "cpp"}


def languages():
    """Return names of supported header backends."""
    return sorted(_BACKENDS)


def generate(text, language="cpp"):
    """Resolve SysML input and render it with the named language backend."""
    backend = _BACKENDS.get(language)
    if backend is None:
        raise HeaderError(
            f"unsupported header language {language!r}; supported: {', '.join(languages())}")
    renderer = import_module(f"{__name__}.{backend}")
    return renderer.render(resolve(text))
