"""Renders imported layouts as SysMLv2 and expands TypeLink items in a model."""
import re

from . import fetch, languages, parser, repository, spec as specmod, sysml
from .model import ImportError_

BEGIN = "// typelink:begin (generated from the linked type; edits are overwritten)"
END = "// typelink:end"
_REGION = re.compile(r"[ \t]*// typelink:begin[^\n]*\n.*?// typelink:end[ \t]*\n?", re.S)
_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_KEYWORDS = {n[1:-1] for n in sysml.SysMLv2Lexer.literalNames if n and re.fullmatch(r"'[a-z]+'", n)}


def quote(name):
    return name if _IDENT.match(name) and name not in _KEYWORDS else "'" + name.replace("'", "\\'") + "'"


def _mult(m):
    if (m.lower, m.upper) == (1, 1):
        return ""
    if m.upper is None:
        return f"[{m.lower}..*]" if m.lower else "[0..*]"
    if m.lower == m.upper:
        return f"[{m.lower}]"
    return f"[{m.lower}..{m.upper}]"


def _size(bits, ind):
    return f"@DataSize {{ bits = {bits}; }}" if bits is not None else None


def render_members(struct, types, ind, emitted):
    out = []
    for sub in struct.nested:
        if sub.name in emitted:
            continue
        emitted.add(sub.name)
        out.append(f"{ind}item def {quote(sub.name)} {{")
        if sub.layout_kind:
            layout = {"struct": "Struct", "union": "Union",
                      "protobuf": "Protobuf"}[sub.layout_kind]
            out.append(f"{ind}    @DataLayout {{ kind = DataLayoutKind::{layout}; }}")
        if sub.bits is not None:
            out.append(f"{ind}    @DataSize {{ bits = {sub.bits}; }}")
        out += render_members(sub, types, ind + "    ", emitted)
        out.append(f"{ind}}}")
    sysml_types = types["sysml"]
    for m in struct.members:
        n, mult = quote(m.name), _mult(m)
        annotations = []
        size = _size(m.bits, ind)
        if size:
            annotations.append(size)
        if m.offset_bits is not None:
            annotations.append(f"@DataOffset {{ bits = {m.offset_bits}; }}")
        if m.signed is not None:
            signed = "true" if m.signed else "false"
            annotations.append(f"@DataSigned {{ value = {signed}; }}")
        if m.wire is not None:
            kind = m.wire.kind.title()
            annotations.append(
                f'@DataEncoding {{ field_number = {m.wire.number}; '
                f'kind = DataEncodingKind::{kind}; wire_type = {m.wire.wire_type}; '
                f'source_type = "{m.wire.source_type}"; '
                f'packed = {"true" if m.wire.packed else "false"}; }}')
            if m.wire.kind == "map":
                annotations.append(
                    f'@DataMap {{ key_type = "{m.wire.key_type}"; '
                    f'value_type = "{m.wire.value_type}"; '
                    f'value_kind = "{m.wire.value_kind}"; }}')
        if m.kind == "unresolved":
            head = f"ref item {n} : {quote(m.type_name)}{mult}"
        else:
            head = (f"item {n} : {quote(m.type_name)}{mult}" if m.kind == "struct"
                    else f"attribute {n} : {sysml_types[m.kind]}{mult}")
        if annotations:
            out.append(f"{ind}{head} {{")
            out.extend(f"{ind}    {annotation}" for annotation in annotations)
            out.append(f"{ind}}}")
        else:
            out.append(f"{ind}{head};")
    return out


def render_region(struct, types, ind):
    lines = [ind + BEGIN]
    if struct.layout_kind:
        layout = {"struct": "Struct", "union": "Union",
                  "protobuf": "Protobuf"}[struct.layout_kind]
        lines.append(f"{ind}@DataLayout {{ kind = DataLayoutKind::{layout}; }}")
    size = _size(struct.bits, ind)
    if size:
        lines.append(ind + size)
    lines += render_members(struct, types, ind, set())
    lines.append(ind + END)
    return "\n".join(lines)


def load_layout(link, data_model=None, text=None, max_bytes=fetch.DEFAULT_MAX_BYTES,
                additional_sources=()):
    source = text if text is not None else fetch.fetch(link.uri, max_bytes)
    return languages.get(link.origin).import_type(
        source, link.element, data_model, additional_sources)


def expand(text, data_model=None, fetcher=None, warn=lambda m: None,
           max_bytes=fetch.DEFAULT_MAX_BYTES, clone_repo=False, additional_sources=()):
    """Return text with every TypeLink-bearing definition body fleshed out."""
    if clone_repo and fetcher is not None:
        raise ValueError("fetcher and clone_repo cannot be used together")
    types = specmod.load_types()
    tree = sysml.parse(text)
    links = parser.extract(tree)
    edits = {}
    for link in links:
        body = link.definition
        if body is None or body.LBRACE() is None or body.start.start in edits:
            continue
        repo_sources = ()
        if clone_repo:
            source, repo_sources = repository.fetch_sources(
                link.uri, link.origin, max_bytes)
        else:
            source = fetcher(link.uri) if fetcher else None
        res = load_layout(link, data_model, source, max_bytes,
                          (*additional_sources, *repo_sources))
        for w in res.warnings:
            warn(f"{link.element}: {w}")
        first = link.link_ctx.start
        line_start = text.rfind("\n", 0, first.start) + 1
        ind = re.match(r"[ \t]*", text[line_start:]).group(0)
        inner = _REGION.sub("", text[body.start.start + 1:body.stop.stop])
        inner = inner.rstrip() + "\n" if inner.strip() else "\n"
        edits[body.start.start] = (body.stop.stop, "{" + inner + render_region(res.struct, types, ind) + "\n"
                                   + ind[:-4 if len(ind) >= 4 else 0] + "}")
    for start in sorted(edits, reverse=True):
        stop, repl = edits[start]
        text = text[:start] + repl + text[stop + 1:]
    sysml.parse(text)   # the output must itself be valid SysMLv2
    return text
