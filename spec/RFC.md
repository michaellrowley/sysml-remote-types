# SysMLv2 Remote Type Links

## 1. Overview

This document specifies `TypeLink`, a SysMLv2 metadata definition marking an
item or type as a shallow reference to a type defined elsewhere (at a URI).

The normative definition is `spec/typelink.sysml`. It is the single source of
truth: the tool in `tool/` loads that file at runtime to obtain the permitted
`TypeOrigin` values and `TypeLink` attributes, and the block below is verbatim
a copy of it (enforced by the test suite). Edit the `.sysml` file, then run
`python3 -m typelink sync-spec` from `tool/` to refresh this document.

## 2. Definition

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

Tools MUST derive the set of valid origins and attributes from the definition
in Section 2.
