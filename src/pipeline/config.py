"""Settings for the Python pipeline. Secrets come from .env (git-ignored), never from code."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "logs"
DOCS_DIR = ROOT / "docs"

# Scraper behaviour (see docs/feasibility.md)
PAGE_TIMEOUT_MS = 30_000
MIN_DELAY_S, MAX_DELAY_S = 2.0, 3.0  # pause between page loads
MAX_RETRIES = 3  # retries after the first attempt (429 / timeout)
BACKOFF_BASE_S = 5.0  # 5s, 10s, 20s
MOCK_TARGET = 30


def load_env() -> None:
    # .env holds the service_role key; .env.local is only used as a fallback for the public URL.
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local")


def supabase_settings() -> tuple[str, str]:
    load_env()
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit(
            "Missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY. Copy .env.example to .env and fill them in "
            "(the service_role key must never go into the frontend or be committed)."
        )
    return url.rstrip("/"), key
