# SysML Remote Type Links

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![SysML v2](https://img.shields.io/badge/SysML-v2-4c6.svg)](spec/RFC.md)
[![Type sources](https://img.shields.io/badge/type%20sources-C%20%7C%20C%2B%2B%20%7C%20Protobuf-556b2f.svg)](spec/RFC.md)

Reference external C, C++, or Protobuf types from SysMLv2, then generate
SysML item bodies from those definitions. The project includes both the
`@TypeLink` specification and a command-line tool to validate links and expand
them with member types and known sizes.

## Quick start

Clone with the pinned grammar submodules, then install the tool dependencies:

```sh
git clone --recurse-submodules https://github.com/michaellrowley/sysml-remote-types.git
cd sysml-remote-types
git submodule update --init --recursive && python -m pip install -e ./tool
```

After installation, `typelink` is available on `PATH` from any working
directory (keep the repository checkout in place). For example:

Add a link to a SysMLv2 item:

```sysml
item def packet {
    @TypeLink {
        origin = TypeOrigin::C;
        uri = "https://example.com/packet.h";
    }
}
```

For example, given this `packet.h`:

```c
#include <stdint.h>
struct header { uint8_t type; uint16_t len; };
struct packet { struct header hdr; uint8_t payload[4]; };
```

`typelink expand` generates the members, sizes, source layout kind, and member
offsets:

```sysml
@DataLayout { kind = DataLayoutKind::Struct; }
@DataSize { bits = 64; }
item def header {
    @DataLayout { kind = DataLayoutKind::Struct; }
    @DataSize { bits = 32; }
    attribute 'type' : ScalarValues::Integer {
        @DataSize { bits = 8; }
        @DataOffset { bits = 0; }
        @DataSigned { value = false; }
    }
    attribute len : ScalarValues::Integer {
        @DataSize { bits = 16; }
        @DataOffset { bits = 16; }
        @DataSigned { value = false; }
    }
}
item hdr : header {
    @DataSize { bits = 32; }
    @DataOffset { bits = 0; }
}
attribute payload : ScalarValues::Integer[4] {
    @DataSize { bits = 8; }
    @DataOffset { bits = 32; }
    @DataSigned { value = false; }
}
```

Run the tool to validate links or generate the item's body:

```sh
typelink check model.sysml
typelink expand model.sysml
```

Expansion writes generated content between `typelink:begin` and `typelink:end`
markers; re-running it replaces that region. See the [RFC](spec/RFC.md) for
the metadata definition, sizing rules, and supported formats.

## Generate Kaitai Struct schemas

`typelink kaitai` resolves `@TypeLink` annotations, expands the SysMLv2 items,
and writes a Kaitai Struct `.ksy` schema. For native SysML items with explicit
data types and `@DataSize`, it treats fields as a packed sequence. Select an
item with `--item` when the file contains more than one top-level item:

```sh
typelink kaitai examples/packet.sysml --item Packet -o packet.ksy
```

The checked-in [SysML input](examples/packet.sysml) and
[generated schema](examples/packet.ksy) show the native packed layout. To
generate from a model that was expanded separately, pass `--expanded`:

```sh
typelink expand model.sysml -o expanded.sysml
typelink kaitai expanded.sysml --item packet --expanded -o packet.ksy
```

For C/C++ links, expansion records member offsets, signedness, struct/union
kind, and sizes; the Kaitai generator inserts padding at the recorded offsets.
Unions are emitted as opaque byte regions because SysML has no discriminator
that selects a union member. For Protobuf links, expansion retains field
numbers, wire kinds, packed-field information, map key/value types, and nested
messages; the generator emits a tagged wire parser rather than treating a
message as an in-memory struct.

Useful options include `--endian le|be` and `--bit-endian le|be` for native and
C/C++ fields (both default to little-endian), and `--integer-signedness` to
choose `signed` or `unsigned` for native SysML `Integer` fields (default
unsigned). `--data-model` selects C/C++ widths during expansion;
`--clone-repo` and `--max-bytes` control GitHub source resolution. Protobuf
fixed-width wire values always use their specified little-endian encoding, and
Protobuf varints use their defined high-bit continuation order. The generated
Protobuf `fields` array preserves wire order; consumers interpret a field by
its tag. See
`typelink kaitai --help` and the
[RFC](spec/RFC.md#7-kaitai-generation) for the complete mapping and
limitations.

Additionally, Expansion reads only the linked file by default. Pass `--clone-repo` to clone
the repository for GitHub `blob` URLs into a temporary directory and include
the repository's tracked C/C++ or Protobuf source files when resolving types.
The checkout is removed after expansion. This is opt-in because cloning can be
slow and repositories can be large. The Python `emit.expand` API exposes the
same option as `clone_repo=True`; importers also accept `additional_sources`
for callers that already manage source context. This indexes matching files
repo-wide; it does not run a compiler/preprocessor or infer build-target
include paths. Git submodule contents are not included.

## Grammar dependencies

The grammars are pinned submodules in `tool/third_party/`. If you cloned
without `--recurse-submodules`, initialize them with
`git submodule update --init`. SysMLv2's generated parser is committed in
`tool/typelink/_sysml/`; rebuild it with `tool/regen_grammar.sh`. The C and C++
grammars are compiled on first use with `cc`.
