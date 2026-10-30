"""Read an Obsidian vault into a link graph (notes + undirected edges)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from urllib.parse import unquote

SKIP_DIRS = {".obsidian", ".git", ".trash", "node_modules"}

# [[target]], [[target|alias]], [[target#heading]], ![[embed]]
WIKILINK = re.compile(r"!?\[\[([^\[\]|#^]*)(?:[#^][^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
# [text](relative/path.md) — only local .md targets
MDLINK = re.compile(r"\[[^\]]*\]\(([^)\s]+?\.md)(?:#[^)]*)?\)")
CODE_FENCE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)
INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass
class Note:
    path: str            # vault-relative, with .md
    title: str           # basename without .md
    folder: str          # top-level folder ("" for root)
    archive: bool
    mtime: float
    links: set[str] = field(default_factory=set)   # resolved vault-relative paths


@dataclass
class Graph:
    notes: list[Note]               # connected notes only (orphans removed)
    edges: list[tuple[int, int]]    # undirected, i < j
    degree: list[int]


def is_archive(rel: str, archive_prefix: str = "") -> bool:
    """Explicit prefix if given, else any top-level folder named like an archive."""
    if archive_prefix:
        return rel.startswith(archive_prefix)
    top = rel.split(os.sep)[0] if os.sep in rel else ""
    return "archive" in top.lower()


def scan(vault: str, archive_prefix: str = "") -> dict[str, Note]:
    notes: dict[str, Note] = {}
    for root, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if not f.endswith(".md"):
                continue
            full = os.path.join(root, f)
            rel = os.path.relpath(full, vault)
            top = rel.split(os.sep)[0] if os.sep in rel else ""
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            notes[rel] = Note(
                path=rel,
                title=f[:-3],
                folder=top,
                archive=is_archive(rel, archive_prefix),
                mtime=mtime,
            )
    return notes


def _resolver(notes: dict[str, Note]):
    by_name: dict[str, list[str]] = {}
    by_path: dict[str, str] = {}
    for rel in notes:
        by_name.setdefault(os.path.basename(rel)[:-3].lower(), []).append(rel)
        by_path[rel[:-3].lower()] = rel

    def resolve(target: str, source: str) -> str | None:
        t = unquote(target).strip().replace("\\", "/")
        if not t:
            return None
        if t.lower().endswith(".md"):
            t = t[:-3]
        # relative markdown-style path from the source note's folder
        if t.startswith("./") or t.startswith("../"):
            t = os.path.normpath(os.path.join(os.path.dirname(source), t))
        key = t.lstrip("/").lower()
        if key in by_path:
            return by_path[key]
        cands = by_name.get(os.path.basename(key))
        if not cands:
            return None
        if len(cands) == 1 or "/" not in key:
            # Obsidian prefers the closest match; approximate with same folder first
            src_dir = os.path.dirname(source)
            for c in cands:
                if os.path.dirname(c) == src_dir:
                    return c
            return sorted(cands, key=len)[0]
        for c in cands:
            if c[:-3].lower().endswith(key):
                return c
        return cands[0]

    return resolve


def parse_links(vault: str, notes: dict[str, Note]) -> None:
    resolve = _resolver(notes)
    for rel, note in notes.items():
        try:
            with open(os.path.join(vault, rel), encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        text = INLINE_CODE.sub("", CODE_FENCE.sub("", text))
        found = set()
        for m in WIKILINK.finditer(text):
            r = resolve(m.group(1), rel)
            if r and r != rel:
                found.add(r)
        for m in MDLINK.finditer(text):
            target = m.group(1)
            if "://" in target:
                continue
            r = resolve(target, rel)
            if r and r != rel:
                found.add(r)
        note.links = found


def build_graph(vault: str, archive_prefix: str = "") -> Graph:
    notes = scan(vault, archive_prefix)
    parse_links(vault, notes)

    pairs: set[tuple[str, str]] = set()
    for rel, note in notes.items():
        for t in note.links:
            a, b = (rel, t) if rel < t else (t, rel)
            pairs.add((a, b))

    connected = sorted({p for pair in pairs for p in pair})
    index = {p: i for i, p in enumerate(connected)}
    edges = sorted((index[a], index[b]) for a, b in pairs)
    degree = [0] * len(connected)
    for a, b in edges:
        degree[a] += 1
        degree[b] += 1
    return Graph([notes[p] for p in connected], edges, degree)


if __name__ == "__main__":
    import sys
    import time

    t0 = time.time()
    g = build_graph(sys.argv[1])
    arch = sum(n.archive for n in g.notes)
    print(f"{len(g.notes)} connected notes ({arch} archive), {len(g.edges)} edges, {time.time()-t0:.2f}s")
    top = sorted(range(len(g.notes)), key=lambda i: -g.degree[i])[:12]
    for i in top:
        print(f"  {g.degree[i]:4d}  {g.notes[i].path}")
