"""Loads source files from an opt-in GitHub repository checkout."""
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from .fetch import DEFAULT_MAX_BYTES


_SOURCE_SUFFIXES = {
    "C": {".c", ".h", ".i", ".inc"},
    "CPP": {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
            ".i", ".inc", ".ipp", ".inl", ".tcc"},
    "Protobuf": {".proto"},
}
_CLONE_TIMEOUT = 300
_GITHUB_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _git(args, timeout=60, check=True):
    try:
        return subprocess.run(
            ["git", *args], check=check, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip()
        raise ValueError(f"git {' '.join(args[:2])} failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"git {' '.join(args[:2])} timed out") from exc


def _blob_location(uri):
    parsed = urlparse(uri)
    parts = [unquote(p) for p in parsed.path.strip("/").split("/")]
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or len(parts) < 5 or parts[2] != "blob"):
        raise ValueError(
            "--clone-repo requires a GitHub file URL in the form "
            "https://github.com/OWNER/REPO/blob/REF/PATH")
    owner, repo = parts[:2]
    location = parts[3:]
    repo = repo.removesuffix(".git")
    if (not _GITHUB_NAME.fullmatch(owner) or not _GITHUB_NAME.fullmatch(repo)
            or owner in (".", "..") or repo in (".", "..")
            or any(p in ("", ".", "..") or "/" in p or "\\" in p or "\0" in p
                   for p in location)):
        raise ValueError(f"invalid GitHub file URL: {uri}")
    return owner, repo, location


def _resolve_location(location, ref_names, repo_dir):
    """Resolve the longest ref prefix and leave the remaining path as the file."""
    refs = {}
    for ref_name, full_ref in ref_names:
        refs.setdefault(ref_name, full_ref)

    for end in range(len(location) - 1, 0, -1):
        candidate = "/".join(location[:end])
        if candidate.startswith("refs/heads/"):
            candidate = candidate[len("refs/heads/"):]
        elif candidate.startswith("refs/tags/"):
            candidate = candidate[len("refs/tags/"):]
        if candidate in refs:
            return refs[candidate], Path(*location[end:])

        result = _git(
            ["-C", str(repo_dir), "cat-file", "-e", f"{candidate}^{{commit}}"],
            check=False)
        if result.returncode == 0:
            return candidate, Path(*location[end:])
    raise ValueError("the GitHub file URL does not identify a repository ref and path")


def _tracked_files(repo_dir):
    result = _git(["-C", str(repo_dir), "ls-files", "-z"])
    return [os.fsdecode(path) for path in result.stdout.split("\0") if path]


def _read_source(repo_dir, relative_path, required=False, max_bytes=None, uri=None):
    root = repo_dir.resolve()
    path = (repo_dir / relative_path).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        if required:
            raise ValueError(f"linked source path escapes the cloned repository: {relative_path}")
        return None
    if not path.is_file():
        if required:
            raise ValueError(f"linked source file not found in cloned repository: {relative_path}")
        return None
    data = path.read_bytes()
    if max_bytes is not None and len(data) > max_bytes:
        raise ValueError(f"{uri} exceeds {max_bytes} bytes (see --max-bytes)")
    return data.decode("utf-8", errors="replace")


def fetch_sources(uri, origin, max_bytes=DEFAULT_MAX_BYTES):
    """Clone a GitHub repository temporarily and return its linked file and peer sources."""
    if origin not in _SOURCE_SUFFIXES:
        raise ValueError(f"repository source collection is unsupported for origin {origin}")
    owner, repo, location = _blob_location(uri)
    remote = f"https://github.com/{owner}/{repo}.git"

    with tempfile.TemporaryDirectory(prefix="typelink-") as temp_dir:
        repo_dir = Path(temp_dir) / "repo"
        _git(["clone", "--quiet", "--no-checkout", remote, str(repo_dir)],
             timeout=_CLONE_TIMEOUT)

        refs_result = _git(
            ["-C", str(repo_dir), "for-each-ref", "--format=%(refname)"])
        ref_names = []
        for ref in refs_result.stdout.splitlines():
            if ref.startswith("refs/remotes/origin/") and not ref.endswith("/HEAD"):
                ref_names.append((ref[len("refs/remotes/origin/"):], ref))
            elif ref.startswith("refs/tags/"):
                ref_names.append((ref[len("refs/tags/"):], ref))
        ref, source_path = _resolve_location(location, ref_names, repo_dir)
        commit = _git(
            ["-C", str(repo_dir), "rev-parse", "--verify", f"{ref}^{{commit}}"])
        _git(["-C", str(repo_dir), "checkout", "--quiet", "--detach",
              commit.stdout.strip()])

        linked_source = _read_source(
            repo_dir, source_path, required=True, max_bytes=max_bytes, uri=uri)
        suffixes = _SOURCE_SUFFIXES[origin]
        source_paths = sorted({
            Path(path) for path in _tracked_files(repo_dir)
            if Path(path).suffix.lower() in suffixes
        })
        source_paths = [source_path] + [p for p in source_paths if p != source_path]
        additional_sources = []
        for path in source_paths[1:]:
            source = _read_source(repo_dir, path)
            if source is not None:
                additional_sources.append(source)
        return linked_source, additional_sources
