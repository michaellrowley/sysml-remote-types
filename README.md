# SysML Remote Type Links

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![SysML v2](https://img.shields.io/badge/SysML-v2-4c6.svg)](spec/RFC.md)
[![Type sources](https://img.shields.io/badge/type%20sources-C%20%7C%20C%2B%2B%20%7C%20Protobuf-556b2f.svg)](spec/RFC.md)

Use SysMLv2 `@TypeLink` annotations to import supported external types and
generate their item bodies. The CLI also generates Kaitai Struct schemas from
imported or native SysMLv2 models, independently of their source format.

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
markers; re-running it replaces that region. Pass a directory to `check` or
`expand` to process its `.sysml` files recursively. `check` combines findings
into its normal JSON output; `expand` rewrites those files in place. See the
[RFC](spec/RFC.md) for the metadata definition, sizing rules, and supported
formats.

## Generate Kaitai Struct schemas

`typelink kaitai` generates a Kaitai Struct `.ksy` schema from an imported
SysMLv2 item. Generation uses the SysML structure and layout metadata only; it
does not depend on the original source language or format. By default, the
command also resolves `@TypeLink` annotations and expands their items first.
For items without an explicit layout, fields with data types and `@DataSize`
are treated as a packed sequence. Select an item with `--item` when the file
contains more than one top-level item:

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

`DataLayout` distinguishes offset-based structures and overlapping unions from
packed sequences. `DataOffset`, `DataSize`, and `DataSigned` provide the layout
facts needed to generate fields and padding; unions are emitted as opaque byte
regions because the model has no discriminator that selects a member. Tagged
wire layouts can carry `DataEncoding` metadata for field tags, wire kinds,
packed fields, maps, and nested types, allowing the generator to emit a wire
parser rather than treating them as in-memory structures.

`--endian le|be` and `--bit-endian le|be` control byte and bit order for
layouts that do not define their own encoding (both default to little-endian).
`--integer-signedness` chooses `signed` or `unsigned` for `Integer` fields
without `DataSigned` metadata (default unsigned). Protocol-defined encodings
retain their required byte and bit order. The generated tagged-wire `fields`
array preserves wire order; consumers interpret a field by its tag. See
`typelink kaitai --help` and the
[RFC](spec/RFC.md#7-kaitai-generation) for the complete mapping and
limitations.

For other import settings, run `typelink expand` first (for example,
`typelink expand model.sysml --data-model MODEL -o expanded.sysml`), then
generate from the resulting SysMLv2 with `typelink kaitai --expanded`.

The optional TypeLink expansion step reads only the linked file by default.
`--max-bytes` caps the fetched resource; `--clone-repo` also indexes tracked
files from its repository when resolving types. The temporary checkout is
removed afterward and submodule contents are excluded. Repository indexing
does not run compilers or infer build-target include paths. The Python
`emit.expand` API also accepts `clone_repo=True` and `additional_sources` for
callers that manage source context themselves.

## Grammar dependencies

The grammars are pinned submodules in `tool/third_party/`. If you cloned
without `--recurse-submodules`, initialize them with
`git submodule update --init`. SysMLv2's generated parser is committed in
`tool/typelink/_sysml/`; rebuild it with `tool/regen_grammar.sh`. The C/C++
source import grammars are compiled on first use with `cc`; Kaitai generation
does not use them.
