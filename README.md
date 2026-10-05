# sysml-remote-types
The specification lives in `spec/` (`RFC.md` is the normative text; it embeds
`typelink.sysml` and `types.json`, which the tool reads). The tool is in `tool/`:

    pip install -r tool/requirements.txt
    cd tool
    python3 -m typelink check model.sysml          # validate @TypeLink usages
    python3 -m typelink expand model.sysml         # generate full item bodies
    python3 -m unittest discover -s tests

SysMLv2 is parsed with the ANTLR grammar from
[daltskin/sysml-v2-grammar](https://github.com/daltskin/sysml-v2-grammar),
vendored in `tool/grammar/` (regenerate the parser with `tool/regen_grammar.sh`).
