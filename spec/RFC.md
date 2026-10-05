# SysMLv2 Remote Type Links

## 1. Overview

This document specifies `TypeLink`, a SysMLv2 metadata definition marking an
item or type as a shallow reference to a type defined elsewhere (at a URI), and
the translation ("expansion") of such a reference into a full SysMLv2 body.

Single source of truth: the two files embedded below, `spec/typelink.sysml`
and `spec/types.json`. The tool in `tool/` loads them at runtime (parsing the
`.sysml` with the SysMLv2 grammar), so changing a file there changes the tool.
The embedded copies are verified by the test suite; refresh them with
`python3 -m typelink sync-spec` from `tool/`.

## 2. Definitions

<!-- BEGIN typelink.sysml -->
```sysml
package TypeLinkMetadata {
    enum def TypeOrigin {
        doc /* Different formats for structural data that may be present
             * in the addressed URI
             */
        enum C;
        enum CPP;
        enum Protobuf;
    }
    metadata def TypeLink {
        doc /* Indicates that a given item/type which uses this TypeLink will
             * act as a shallow reference to the linked type.
             */
        attribute origin : TypeOrigin;
        attribute uri : String;
    }
    metadata def DataSize {
        doc /* Size, in bits, of one instance of the annotated member, or of the
             * whole item when it annotates an item definition (including any
             * padding the origin's layout rules insert). Absent when the size
             * is variable or unknown.
             */
        attribute bits : Natural;
    }
}
```
<!-- END typelink.sysml -->

## 3. Usage

```sysml
item def lell_packet {
    @TypeLink {
        origin = TypeOrigin::C;
        uri = "https://github.com/greatscottgadgets/libbtbb/blob/master/lib/src/bluetooth_le_packet.h";
    }
}
```

## 4. Conformance

A conforming model:

- Provides exactly one `origin`, whose value is a `TypeOrigin` literal.
- Provides exactly one `uri`, an absolute URI string.
- Treats the annotated element as a shallow reference: its structure is
  defined by the linked resource, not by the element body.

Tools MUST derive the valid origins and attributes from Section 2 and MUST
parse SysMLv2 with a grammar-based parser.

## 5. Expansion

Expansion locates, in the resource at `uri`, the struct / union / class
(`C`, `CPP`) or message (`Protobuf`) whose name equals the annotated
definition's name, and generates the following inside the definition body,
between the marker comments `// typelink:begin` and `// typelink:end`
(regenerated in place on every run):

- `@DataSize { bits = N; }` for the whole item, when its total size is known.
- One `attribute` (scalar members) or `item` (aggregate members) per member,
  typed per `types.json` (`sysml` gives the SysMLv2 type of each kind),
  carrying `@DataSize` with the size in bits of ONE instance.
- Array members use multiplicity (`[4]`); protobuf `repeated` is `[0..*]` and
  `optional` is `[0..1]`.
- Aggregate member types are emitted as nested `item def`s.
- Members whose type cannot be resolved become `ref item name : Type;` with no
  `@DataSize`, and the total size of the enclosing item is then omitted.
- Names that are SysMLv2 keywords or not plain identifiers are quoted.

Sizes:

- `C`/`CPP`: scalar widths come from `types.json` (`data_models` selects the
  widths of `long` and pointers; `default_data_model` applies unless chosen).
  Layout uses natural alignment (alignment = size, capped at 128 bits), bit
  fields packed within their declared type's storage unit, union size = largest
  member, and total size padded to the largest alignment. `#pragma pack` and
  base classes are not modelled (a total size is then omitted for base classes).
- `Protobuf`: member size is the nominal declared width from `protobuf_scalars`;
  `string`/`bytes`, maps and messages have no size. No total is given, as wire
  size is variable.

The expanded output MUST itself be valid SysMLv2.

<!-- BEGIN types.json -->
```json
{
  "sysml": {
    "integer": "ScalarValues::Integer",
    "real": "ScalarValues::Real",
    "boolean": "ScalarValues::Boolean",
    "string": "ScalarValues::String"
  },
  "data_models": {
    "ilp32": {"char": 8, "short": 16, "int": 32, "long": 32, "long long": 64, "pointer": 32},
    "lp64": {"char": 8, "short": 16, "int": 32, "long": 64, "long long": 64, "pointer": 64},
    "llp64": {"char": 8, "short": 16, "int": 32, "long": 32, "long long": 64, "pointer": 64}
  },
  "default_data_model": "lp64",
  "c_scalars": {
    "bool": ["boolean", 8], "_Bool": ["boolean", 8],
    "float": ["real", 32], "double": ["real", 64], "long double": ["real", 128],
    "int8_t": ["integer", 8], "uint8_t": ["integer", 8],
    "int16_t": ["integer", 16], "uint16_t": ["integer", 16],
    "int32_t": ["integer", 32], "uint32_t": ["integer", 32],
    "int64_t": ["integer", 64], "uint64_t": ["integer", 64],
    "size_t": ["integer", "pointer"], "ssize_t": ["integer", "pointer"],
    "intptr_t": ["integer", "pointer"], "uintptr_t": ["integer", "pointer"]
  },
  "protobuf_scalars": {
    "double": ["real", 64], "float": ["real", 32],
    "int32": ["integer", 32], "int64": ["integer", 64],
    "uint32": ["integer", 32], "uint64": ["integer", 64],
    "sint32": ["integer", 32], "sint64": ["integer", 64],
    "fixed32": ["integer", 32], "fixed64": ["integer", 64],
    "sfixed32": ["integer", 32], "sfixed64": ["integer", 64],
    "bool": ["boolean", 8],
    "string": ["string", null], "bytes": ["string", null]
  }
}
```
<!-- END types.json -->
