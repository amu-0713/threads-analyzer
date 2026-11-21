"""Text features for a post. Pure functions, no I/O."""

from __future__ import annotations

import re

# Links: explicit scheme / www., or a bare domain (Threads often shows links without a scheme).
URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"
    r"|(?<![\w@.])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|tw|net|org|io|co|me|ly|gl|link|tv|app)(?:/[^\s<>\"']*)?(?![\w-])",
    re.I,
)
HASHTAG_RE = re.compile(r"(?<![\w&#])#\w+")
MENTION_RE = re.compile(r"(?<![\w@.])@[A-Za-z0-9._]{1,30}")

POST_TYPES = ("含連結", "含 hashtag", "含 mention", "純文字")


def text_features(text: str | None) -> dict:
    text = text or ""
    urls = URL_RE.findall(text)
    rest = URL_RE.sub(" ", text)  # don't count "#anchor" / "@user" inside URLs
    hashtags = HASHTAG_RE.findall(rest)
    mentions = MENTION_RE.findall(rest)
    feats = {
        "char_count": len(text),
        "hashtag_count": len(hashtags),
        "mention_count": len(mentions),
        "url_count": len(urls),
    }
    feats["post_type"] = post_type(feats)
    return feats


def post_type(f: dict) -> str:
    """One label per post; when several apply the order is link > hashtag > mention > plain text."""
    if f["url_count"]:
        return "含連結"
    if f["hashtag_count"]:
        return "含 hashtag"
    if f["mention_count"]:
        return "含 mention"
    return "純文字"
