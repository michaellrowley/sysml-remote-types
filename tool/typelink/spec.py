"""Loads the normative TypeLink definition from spec/typelink.sysml."""
import re
from pathlib import Path

SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"
SPEC_FILE = SPEC_DIR / "typelink.sysml"
RFC_FILE = SPEC_DIR / "RFC.md"
_BLOCK = re.compile(
    r"(<!-- BEGIN typelink\.sysml -->\n```sysml\n)(.*?)(```\n<!-- END typelink\.sysml -->)",
    re.S)


def load(path=SPEC_FILE):
    text = Path(path).read_text()
    enum = re.search(r"enum def TypeOrigin\s*\{(.*?)\n\s*\}", text, re.S).group(1)
    origins = re.findall(r"^\s*enum\s+(\w+)\s*;", enum, re.M)
    meta = re.search(r"metadata def TypeLink\s*\{(.*?)\n\s*\}", text, re.S).group(1)
    attrs = dict(re.findall(r"attribute\s+(\w+)\s*:\s*(\w+)\s*;", meta))
    return origins, attrs


def sync_rfc(rfc=RFC_FILE, spec=SPEC_FILE, write=True):
    """Embed the spec in the RFC. Returns True if the RFC was up to date."""
    old = Path(rfc).read_text()
    new = _BLOCK.sub(lambda m: m.group(1) + Path(spec).read_text() + m.group(3), old)
    if new != old and write:
        Path(rfc).write_text(new)
    return new == old
