"""Builds and loads tree-sitter grammars from the pinned submodules in third_party/."""
import ctypes
import subprocess
import sys
import sysconfig
from pathlib import Path

from tree_sitter import Language, Parser

THIRD_PARTY = Path(__file__).resolve().parents[1] / "third_party"
BUILD_DIR = Path(__file__).resolve().parents[1] / ".build"
_loaded = {}


def language(repo, symbol):
    """Language for submodule `repo` (dir under third_party/); `symbol` is its
    exported entry point, e.g. 'tree_sitter_c'."""
    if repo in _loaded:
        return _loaded[repo]
    src = THIRD_PARTY / repo / "src"
    if not (src / "parser.c").exists():
        raise RuntimeError(
            f"{src}/parser.c missing; run `git submodule update --init --recursive`")
    suffix = ".dll" if sys.platform == "win32" else ".dylib" if sys.platform == "darwin" else ".so"
    lib = BUILD_DIR / f"{repo}{suffix}"
    sources = sorted(src.glob("*.c"))
    if not lib.exists() or lib.stat().st_mtime < max(s.stat().st_mtime for s in sources):
        BUILD_DIR.mkdir(exist_ok=True)
        cc = sysconfig.get_config_var("CC") or "cc"
        subprocess.run(cc.split() + ["-shared", "-fPIC", "-O2", "-I", str(src),
                                     *map(str, sources), "-o", str(lib)], check=True)
    handle = ctypes.cdll.LoadLibrary(str(lib))
    fn = getattr(handle, symbol)
    fn.restype = ctypes.c_void_p
    new_capsule = ctypes.pythonapi.PyCapsule_New
    new_capsule.restype = ctypes.py_object
    new_capsule.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p]
    capsule = new_capsule(fn(), b"tree_sitter.Language", None)
    _loaded[repo] = (handle, Language(capsule))   # keep handle alive
    return _loaded[repo]


def get_language(repo, symbol):
    return language(repo, symbol)[1]


def parser_for(repo, symbol):
    return Parser(get_language(repo, symbol))
