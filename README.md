# sysml-remote-types
The specification lives in `spec/` (`RFC.md` is the normative text; it embeds
`typelink.sysml` and `types.json`, which the tool reads). The tool is in `tool/`:

    pip install -r tool/requirements.txt
    cd tool
    python3 -m typelink check model.sysml          # validate @TypeLink usages
    python3 -m typelink expand model.sysml         # generate full item bodies
    python3 -m unittest discover -s tests

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
