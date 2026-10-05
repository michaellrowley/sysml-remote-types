#!/bin/sh
# Regenerates typelink/_sysml/ from the pinned submodule (ANTLR 4.13.2).
set -e
cd "$(dirname "$0")"
git submodule update --init third_party/sysml-v2-grammar
cd third_party/sysml-v2-grammar/grammar
antlr4 -v 4.13.2 -Dlanguage=Python3 -no-listener -o ../../../typelink/_sysml SysMLv2Lexer.g4 SysMLv2Parser.g4
rm -f ../../../typelink/_sysml/*.interp ../../../typelink/_sysml/*.tokens
