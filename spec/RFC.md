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
    enum def DataLayoutKind {
        enum Struct;
        enum Union;
        enum Protobuf;
    }
    enum def DataEncodingKind {
        enum Varint;
        enum Zigzag;
        enum Fixed32;
        enum Fixed64;
        enum String;
        enum Bytes;
        enum Message;
        enum Enum;
        enum Map;
        enum Group;
        enum Unresolved;
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
             * padding required by the represented layout). Absent when the size
             * is variable or unknown.
             */
        attribute bits : Natural;
    }
    metadata def DataLayout {
        doc /* Layout semantics for Kaitai generation. Struct describes an
             * offset-based layout; Union describes overlapping members;
             * Protobuf describes its tagged wire format. With no DataLayout,
             * fields are a packed sequence.
             */
        attribute kind : DataLayoutKind;
    }
    metadata def DataOffset {
        doc /* Start offset, in bits, of one member from its containing item.
             */
        attribute bits : Natural;
    }
    metadata def DataSigned {
        doc /* Signedness of an integer member in the imported type definition.
             */
        attribute value : Boolean;
    }
    metadata def DataEncoding {
        doc /* Tagged-wire information retained for Kaitai generation.
             */
        attribute field_number : Natural;
        attribute kind : DataEncodingKind;
        attribute wire_type : Natural;
        attribute source_type : String;
        attribute packed : Boolean;
    }
    metadata def DataMap {
        doc /* Key and value types for a tagged-wire map entry.
             */
        attribute key_type : String;
        attribute value_type : String;
        attribute value_kind : String;
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

By default, expansion reads only the resource at `uri`; it does not follow
includes or imports. An implementation MAY offer an opt-in repository-context
mode for GitHub `blob` URLs. In that mode it clones the linked repository to a
temporary directory and makes the repository's tracked source files available
to the language importer when resolving referenced types. Submodule contents
are not included. This does not run a compiler or infer build-target include
paths.

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
  Implementation-defined `char` signedness is recorded only when known
  explicitly.
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

## 6. Binary layout metadata

Expansion adds metadata needed to describe binary layouts without asking the
Kaitai generator to infer missing facts:

- `@DataLayout { kind = DataLayoutKind::Struct; }` marks an offset-based
  structure. `@DataOffset { bits = N; }` on each member records its start
  offset from the containing item. `@DataSigned { value = true|false; }`
  records integer signedness when it is known. `DataLayoutKind::Union` marks
  overlapping members.
- Tagged-wire message definitions use `DataLayoutKind::Protobuf`. Every field
  carries `@DataEncoding` with its field number, wire kind, numeric wire type,
  source type, and declared packed setting. Map fields also carry `@DataMap`
  with their key type, value type, and whether the value is scalar, enum,
  message, or unresolved. Repeated packable fields record the declared packed
  setting; a decoder accepts both packed and unpacked representations.
- With no `@DataLayout`, an item is a packed sequence. Its members still need
  enough type and `@DataSize` information to determine their representation.

Offsets use bits, like `DataSize`. Layout metadata describes the imported
representation; generation consumes these facts as recorded and does not infer
source-language layout rules. Tagged-wire maps and nested messages retain their
wire-level type information; deprecated groups are marked but cannot be
emitted as Kaitai schemas.

## 7. Kaitai generation

The `kaitai` command expands `@TypeLink` items by default, then generates one
`.ksy` schema for one SysML item definition:

```sh
typelink kaitai model.sysml --item packet -o packet.ksy
```

If the input has exactly one top-level item, `--item` may be omitted. When a
model has already been expanded, `--expanded` skips fetching and expansion:

```sh
typelink expand model.sysml -o expanded.sysml
typelink kaitai expanded.sysml --item packet --expanded -o packet.ksy
```

The command also accepts `--clone-repo` and `--max-bytes` for the optional
expansion step. `--endian le|be` sets byte order for fixed-width fields whose
encoding does not specify one (default `le`); `--bit-endian le|be` sets KSY
bit-field order (default `le`). `--integer-signedness signed|unsigned` chooses
a default for `ScalarValues::Integer` fields when no `DataSigned` annotation
is present (default `unsigned`). Protocol-defined fixed-width values retain
their required byte order. For other import settings, run `typelink expand`
first (for example, to set `--data-model`), then generate with `--expanded`.

Field mappings:

- `Integer`, `Natural`, and `Positive` use `u1`, `u2`, `u4`, or `u8` for
  byte-sized widths; other widths up to 64 bits use `bN`. Signed integer
  bit-fields expose a sign-extended `*_signed` instance.
- `Real` supports 32- and 64-bit fields as `f4` and `f8`. `Boolean` uses
  `u1` for 8-bit fields and `bN` for other widths. `String` requires a known,
  byte-aligned `DataSize` and is emitted as a UTF-8 `str`.
- Fixed multiplicities become `repeat: expr`. A final `0..*` field becomes
  `repeat: eos`; other bounded variable multiplicities, unresolved types,
  unknown scalar sizes, and unsupported real widths are errors rather than
  guessed output.
- Offset-based structures use `DataOffset` and `DataSize` to add inter-member
  and tail padding. Unions consume their known size as opaque bytes because no
  discriminator identifies which member to decode.
- Tagged-wire fields are parsed in wire order as a repeated `fields` sequence.
  Each entry dispatches by its encoded tag, decoding varints (including signed
  and zig-zag values), fixed-width values, strings, bytes, nested messages,
  packed repeated values, and map entries. Unknown fields with wire types 0, 1,
  2, and 5 remain parseable as raw values; groups (wire types 3 and 4) are
  unsupported. Consumers interpret entries by tag; the `fields` sequence
  preserves wire order and does not collapse oneof or repeated-field semantics.

The generator normalizes item and field names to Kaitai identifiers. It emits
the selected item as the schema root and its nested item definitions as Kaitai
types. `examples/packet.sysml` and `examples/packet.ksy` are a native packed
SysML input and its generated output.
