"""SysMLv2 parsing, backed by the ANTLR grammar vendored from daltskin/sysml-v2-grammar."""
from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener
from antlr4.tree.Tree import TerminalNode

from ._sysml.SysMLv2Lexer import SysMLv2Lexer
from ._sysml.SysMLv2Parser import SysMLv2Parser

P = SysMLv2Parser


class SysMLSyntaxError(ValueError):
    pass


class _Collect(ErrorListener):
    def __init__(self):
        self.errors = []

    def syntaxError(self, recognizer, symbol, line, column, msg, e):
        self.errors.append(f"line {line}:{column}: {msg}")


def parse(text):
    """Parse SysMLv2 text; returns the RootNamespace context. Raises on syntax errors."""
    errs = _Collect()
    lexer = SysMLv2Lexer(InputStream(text))
    lexer.removeErrorListeners()
    lexer.addErrorListener(errs)
    parser = SysMLv2Parser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(errs)
    tree = parser.rootNamespace()
    if errs.errors:
        raise SysMLSyntaxError("; ".join(errs.errors[:5]))
    return tree


def walk(ctx):
    """Pre-order iteration over all rule contexts below (and including) ctx."""
    stack = [ctx]
    while stack:
        n = stack.pop()
        if isinstance(n, TerminalNode):
            continue
        yield n
        stack.extend(reversed(list(n.getChildren())))


def find_all(ctx, cls):
    return (n for n in walk(ctx) if isinstance(n, cls))


def find_first(ctx, cls):
    return next(find_all(ctx, cls), None)


def decl_name(ctx):
    """Name from the first Identification at or below ctx."""
    ident = find_first(ctx, P.IdentificationContext)
    return ident.getText() if ident else None


def ancestor(ctx, cls):
    while ctx is not None and not isinstance(ctx, cls):
        ctx = ctx.parentCtx
    return ctx


def source_text(text, ctx):
    return text[ctx.start.start:ctx.stop.stop + 1]
