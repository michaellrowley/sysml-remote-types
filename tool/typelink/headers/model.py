"""Language-neutral model for generated source headers."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Field:
    """A typed field or behavior parameter."""
    name: str
    type_name: str
    lower: int = 1
    upper: Optional[int] = 1
    direction: str = "in"
    bits: Optional[int] = None
    offset_bits: Optional[int] = None
    alternatives: List[str] = field(default_factory=list)


@dataclass
class Record:
    """A SysML item definition and its generated members."""
    name: str
    fields: List[Field] = field(default_factory=list)
    bases: List[str] = field(default_factory=list)
    bits: Optional[int] = None
    nested: List["Record"] = field(default_factory=list)


@dataclass
class Function:
    """A behavior translated to a generated function stub."""
    name: str
    parameters: List[Field] = field(default_factory=list)
    connections: List[str] = field(default_factory=list)


@dataclass
class Namespace:
    """A namespace containing nested namespaces, records, and functions."""
    name: str
    namespaces: List["Namespace"] = field(default_factory=list)
    records: List[Record] = field(default_factory=list)
    functions: List[Function] = field(default_factory=list)


@dataclass
class Module:
    """Resolved declarations from one SysML source document."""
    root: Namespace = field(default_factory=lambda: Namespace(""))
