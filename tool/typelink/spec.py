"""Loads the normative definitions from spec/ (the single source of truth)."""
import json
import re
from pathlib import Path

from . import sysml

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
SPEC_FILE = SPEC_DIR / "typelink.sysml"
TYPES_FILE = SPEC_DIR / "types.json"
RFC_FILE = SPEC_DIR / "RFC.md"

# spec files embedded verbatim in the RFC: name -> code fence language
EMBEDDED = {"typelink.sysml": "sysml", "types.json": "json"}


class Spec:
    def __init__(self, origins, metadata):
        self.origins = origins          # ['C', 'CPP', 'Protobuf']
        self.metadata = metadata        # {'TypeLink': {'origin': 'TypeOrigin', ...}, ...}

    @property
    def link_attrs(self):
        return self.metadata["TypeLink"]


def load(path=SPEC_FILE):
    tree = sysml.parse(Path(path).read_text())
    P = sysml.P
    origins, metadata = None, {}
    for e in sysml.find_all(tree, P.EnumerationDefinitionContext):
        if sysml.decl_name(e.definitionDeclaration()) == "TypeOrigin":
            origins = [sysml.decl_name(v) for v in sysml.find_all(e, P.EnumeratedValueContext)]
    for m in sysml.find_all(tree, P.MetadataDefinitionContext):
        attrs = {}
        for a in sysml.find_all(m, P.AttributeUsageContext):
            typing = sysml.find_first(a, P.OwnedFeatureTypingContext)
            attrs[sysml.decl_name(a)] = typing.getText()
        metadata[sysml.decl_name(m.definition().definitionDeclaration())] = attrs
    if origins is None or "TypeLink" not in metadata:
        raise ValueError(f"{path}: missing TypeOrigin or TypeLink definition")
    return Spec(origins, metadata)


def load_types(path=TYPES_FILE):
    return json.loads(Path(path).read_text())


def _block(name, lang):
    return re.compile(
        rf"(<!-- BEGIN {re.escape(name)} -->\n```{lang}\n)(.*?)(```\n<!-- END {re.escape(name)} -->)", re.S)


def sync_rfc(rfc=RFC_FILE, spec_dir=SPEC_DIR, write=True):
    """Embed the spec files in the RFC. Returns True if the RFC was already up to date."""
    old = Path(rfc).read_text()
    new = old
    for name, lang in EMBEDDED.items():
        body = (Path(spec_dir) / name).read_text()
        new = _block(name, lang).sub(lambda m: m.group(1) + body + m.group(3), new)
    if new != old and write:
        Path(rfc).write_text(new)
    return new == old
