"""Minimal .env loader. No dependency, no magic, no overwriting real env vars."""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path = ".env", *, override: bool = False) -> dict[str, str]:
    """Read KEY=VALUE lines. Existing environment wins unless override is set,
    so a value exported in the shell is never silently replaced by a stale file."""
    p = Path(path)
    loaded: dict[str, str] = {}
    if not p.exists():
        return loaded
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not value:
            continue
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded
