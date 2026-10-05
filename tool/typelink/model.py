"""Language-neutral layout model produced by importers and consumed by the emitter."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Member:
    name: str
    kind: str                      # integer | real | boolean | string | struct | unresolved
    bits: Optional[int] = None     # size of ONE instance, None when variable/unknown
    type_name: Optional[str] = None  # for struct / unresolved
    lower: int = 1                 # multiplicity bounds; upper None means unbounded
    upper: Optional[int] = 1


@dataclass
class Struct:
    name: str
    members: List[Member] = field(default_factory=list)
    bits: Optional[int] = None
    nested: List["Struct"] = field(default_factory=list)  # types referenced by struct members


@dataclass
class Result:
    struct: Struct
    warnings: List[str] = field(default_factory=list)


class ImportError_(ValueError):
    pass


def align_up(value, align):
    return -(-value // align) * align
