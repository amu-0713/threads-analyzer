"""Normalize "@name" / a Threads profile or post URL to a bare lowercase username (mirrors src/lib/username.ts)."""

from __future__ import annotations

import re

USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")
_URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?threads\.(?:com|net)/@([^/?#\s]+)", re.I)
_OTHER_URL_RE = re.compile(r"^(?:https?://)?[^/\s]+\.[^/\s]+/", re.I)


def normalize_username(text: str) -> str | None:
    s = text.strip()
    if not s:
        return None
    m = _URL_RE.match(s)
    if m:
        s = m.group(1)
    elif _OTHER_URL_RE.match(s):
        return None
    s = s.lstrip("@").lower() if s.startswith("@") else s.lower()
    return s if USERNAME_RE.match(s) else None
