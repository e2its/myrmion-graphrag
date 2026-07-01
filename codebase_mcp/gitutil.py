"""Utilidades git: SHA/branch actuales y ficheros cambiados respecto a una ref.

Subprocess a `git` real (testeable con un repo temporal). Toda función degrada a valores
neutros si no hay repo git o git no está disponible.
"""

from __future__ import annotations

import subprocess


def _run(args, cwd):
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout


def current_sha(cwd=".") -> str:
    out = _run(["rev-parse", "HEAD"], cwd)
    return out.strip() if out else ""


def current_branch(cwd=".") -> str:
    out = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return out.strip() if out else ""


def commit_time(cwd=".", ref="HEAD") -> str:
    out = _run(["show", "-s", "--format=%cI", ref], cwd)
    return out.strip() if out else ""


def changed_files(git_ref, cwd=".") -> list:
    """Ficheros cambiados entre `git_ref` y el working tree, incluidos los nuevos sin trackear."""
    files = set()
    out = _run(["diff", "--name-only", git_ref], cwd)
    if out:
        files.update(line.strip() for line in out.splitlines() if line.strip())
    others = _run(["ls-files", "--others", "--exclude-standard"], cwd)
    if others:
        files.update(line.strip() for line in others.splitlines() if line.strip())
    return sorted(files)


def is_dirty(cwd=".") -> bool:
    out = _run(["status", "--porcelain"], cwd)
    return bool(out and out.strip())
