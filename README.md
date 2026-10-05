# sysml-remote-types
The specification lives in `spec/` (`RFC.md` is the normative text; it embeds
`typelink.sysml` and `types.json`, which the tool reads). The tool is in `tool/`:

    pip install -r tool/requirements.txt
    cd tool
    python3 -m typelink check model.sysml          # validate @TypeLink usages
    python3 -m typelink expand model.sysml         # generate full item bodies
    python3 -m unittest discover -s tests

Expansion reads only the linked file by default. Pass `--clone-repo` to clone
the repository for GitHub `blob` URLs into a temporary directory and include
the repository's tracked C/C++ or Protobuf source files when resolving types.
The checkout is removed after expansion. This is opt-in because cloning can be
slow and repositories can be large. The Python `emit.expand` API exposes the
same option as `clone_repo=True`; importers also accept `additional_sources`
for callers that already manage source context. This indexes matching files
repo-wide; it does not run a compiler/preprocessor or infer build-target
include paths. Git submodule contents are not included.

Grammars are pinned git submodules in `tool/third_party/` (clone with
`--recurse-submodules`, or run `git submodule update --init`):

- [daltskin/sysml-v2-grammar](https://github.com/daltskin/sysml-v2-grammar) - SysMLv2
  (ANTLR; the generated parser is committed in `tool/typelink/_sysml/`, rebuild with
  `tool/regen_grammar.sh`)
- [tree-sitter/tree-sitter-c](https://github.com/tree-sitter/tree-sitter-c) and
  [tree-sitter-cpp](https://github.com/tree-sitter/tree-sitter-cpp) - C / C++ (compiled
  on first use with `cc`)

Protobuf uses the pinned `proto-schema-parser` package. Language support is a registry
(`tool/typelink/languages/`); see its docstring for how to add Rust or others.

## Worked example: `expand`

Given `packet.h`:

```c
#include <stdint.h>
struct header { uint8_t type; uint16_t len; };
struct packet { struct header hdr; uint8_t payload[4]; };
```

and a model that only links to it:

```sysml
item def packet {
    @TypeLink {
        origin = TypeOrigin::C;
        uri = "https://example.com/packet.h";
    }
}
```

`python3 -m typelink expand model.sysml` fills in the body (sizes are in bits; the
generated region sits between the `typelink:` markers and is replaced on re-runs):

```sysml
item def packet {
    @TypeLink {
        origin = TypeOrigin::C;
        uri = "https://example.com/packet.h";
    }
    // typelink:begin (generated from the linked type; edits are overwritten)
    @DataSize { bits = 64; }
    item def header {
        @DataSize { bits = 32; }
        attribute 'type' : ScalarValues::Integer { @DataSize { bits = 8; } }
        attribute len : ScalarValues::Integer { @DataSize { bits = 16; } }
    }
    item hdr : header { @DataSize { bits = 32; } }
    attribute payload : ScalarValues::Integer[4] { @DataSize { bits = 8; } }
    // typelink:end
}
```

Linked files larger than 8 MiB are refused; change this with `--max-bytes N`.
