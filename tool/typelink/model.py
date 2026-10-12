"""Language-neutral layout model produced by importers and consumed by the emitter."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Member:
    """One field in a source type, with optional layout and wire metadata."""
    name: str
    kind: str                      # integer | real | boolean | string | struct | unresolved
    bits: Optional[int] = None     # size of ONE instance, None when variable/unknown
    type_name: Optional[str] = None  # for struct / unresolved
    lower: int = 1                 # multiplicity bounds; upper None means unbounded
    upper: Optional[int] = 1
    offset_bits: Optional[int] = None
    signed: Optional[bool] = None
    wire: Optional["WireField"] = None


@dataclass
class WireField:
    """Protocol-level field details retained for wire-format generators."""
    number: int
    kind: str
    source_type: str
    wire_type: int
    packed: bool = False
    key_type: Optional[str] = None
    value_type: Optional[str] = None
    value_kind: Optional[str] = None


@dataclass
class Struct:
    """Named aggregate plus its members and any referenced nested types."""
    name: str
    members: List[Member] = field(default_factory=list)
    bits: Optional[int] = None
    nested: List["Struct"] = field(default_factory=list)  # types referenced by struct members
    layout_kind: Optional[str] = None


@dataclass
class Result:
    """Importer result: the normalized type plus non-fatal limitations."""
    struct: Struct
    warnings: List[str] = field(default_factory=list)


class ImportError_(ValueError):
    """A source importer cannot resolve or represent the requested type."""

    pass


def align_up(value, align):
    """Round a bit offset up to the next alignment boundary."""
    return -(-value // align) * align
