#!/bin/sh
# Regenerates typelink/_sysml/ from the vendored grammar (ANTLR 4.13.2).
set -e
cd "$(dirname "$0")/grammar"
antlr4 -v 4.13.2 -Dlanguage=Python3 -no-listener -o ../typelink/_sysml SysMLv2Lexer.g4 SysMLv2Parser.g4
rm -f ../typelink/_sysml/*.interp ../typelink/_sysml/*.tokens
