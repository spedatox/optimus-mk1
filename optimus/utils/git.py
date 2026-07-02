"""
utils/git.py — partial port of src/utils/git.ts

find_canonical_git_root mirrors findCanonicalGitRoot: the main repo working
directory for project identity (so all worktrees of a repo share state).

Porting note: the TS version resolves git worktrees through `.git` gitdir
back-links with a security check against worktree-borrowing attacks. This port
implements the common path — walk up for a `.git` entry — and resolves a
worktree's `.git` *file* to its main repo. The full adversarial back-link
verification is marked RE-ENTRY for when the git worktree hardening lands.
"""
from __future__ import annotations

import os
import unicodedata
from functools import lru_cache
from typing import Optional


def _find_git_dir(start_path: str) -> Optional[str]:
    """Walk up from start_path; return the directory containing `.git`, or None."""
    current = os.path.abspath(start_path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


@lru_cache(maxsize=50)
def find_git_root(start_path: str) -> Optional[str]:
    """
    Port of findGitRoot() — the worktree directory containing `.git` (file or
    dir), or None. Unlike find_canonical_git_root, this does NOT resolve a
    linked worktree back to its main repo.
    """
    return _find_git_dir(start_path)


@lru_cache(maxsize=50)
def find_canonical_git_root(start_path: str) -> Optional[str]:
    """
    Return the canonical git root for project identity, or None if not in a repo.
    Resolves a worktree `.git` *file* (`gitdir: <path>`) back to the main repo.
    """
    git_root = _find_git_dir(start_path)
    if git_root is None:
        return None

    dot_git = os.path.join(git_root, ".git")
    # In a linked worktree, `.git` is a file ("gitdir: <path>/.git/worktrees/x").
    if os.path.isfile(dot_git):
        try:
            with open(dot_git, encoding="utf-8") as f:
                line = f.read().strip()
            if line.startswith("gitdir:"):
                worktree_git_dir = line[len("gitdir:") :].strip()
                # .../.git/worktrees/<name> → main repo is three levels up.
                # RE-ENTRY: full back-link security verification (git.ts).
                common = os.path.dirname(os.path.dirname(os.path.dirname(worktree_git_dir)))
                main_root = os.path.dirname(common) if os.path.basename(common) == ".git" else common
                return unicodedata.normalize("NFC", main_root)
        except OSError:
            return unicodedata.normalize("NFC", git_root)

    return unicodedata.normalize("NFC", git_root)
