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
pip install -r tool/requirements.txt
```

Add a link to a SysMLv2 item:

```sysml
item def packet {
    @TypeLink {
        origin = TypeOrigin::C;
        uri = "https://example.com/packet.h";
    }
}
```

Run the tool from `tool/` to validate links or generate the item's body:

```sh
cd tool
python3 -m typelink check model.sysml
python3 -m typelink expand model.sysml
python3 -m unittest discover -s tests
```

Expansion writes generated content between `typelink:begin` and `typelink:end`
markers; re-running it replaces that region. See the [RFC](spec/RFC.md) for
the metadata definition, sizing rules, and supported formats.

## Grammar dependencies

The grammars are pinned submodules in `tool/third_party/`. If you cloned
without `--recurse-submodules`, initialize them with
`git submodule update --init`. SysMLv2's generated parser is committed in
`tool/typelink/_sysml/`; rebuild it with `tool/regen_grammar.sh`. The C and C++
grammars are compiled on first use with `cc`.
