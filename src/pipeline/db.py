"""Minimal PostgREST client (service_role). Bypasses RLS, so it is backend-only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import supabase_settings


class Db:
    def __init__(self, url: str | None = None, key: str | None = None):
        if url is None or key is None:
            url, key = supabase_settings()
        headers = {"apikey": key, "Content-Type": "application/json"}
        # Legacy service_role keys are JWTs and also go in Authorization. New-style
        # sb_secret_ keys are not JWTs: they must only be sent in the apikey header.
        if key.count(".") == 2:
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.Client(base_url=f"{url}/rest/v1", headers=headers, timeout=30)

    def _check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")
        return r

    def select(self, table: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
        return self._check(self.http.get(f"/{table}", params=params)).json()

    def insert(self, table: str, row: dict) -> dict:
        r = self._check(self.http.post(f"/{table}", json=row, headers={"Prefer": "return=representation"}))
        return r.json()[0]

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        if not rows:
            return
        self._check(
            self.http.post(
                f"/{table}",
                params={"on_conflict": on_conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=rows,
            )
        )

    def update(self, table: str, filters: dict[str, str], values: dict) -> None:
        self._check(self.http.patch(f"/{table}", params=filters, json=values, headers={"Prefer": "return=minimal"}))

    def delete(self, table: str, filters: dict[str, str]) -> None:
        self._check(self.http.delete(f"/{table}", params=filters, headers={"Prefer": "return=minimal"}))

    # --- jobs -------------------------------------------------------------
    def get_job(self, job_id: str) -> dict | None:
        rows = self.select("jobs", {"id": f"eq.{job_id}", "select": "*"})
        return rows[0] if rows else None

    def pending_jobs(self) -> list[dict]:
        return self.select("jobs", {"status": "eq.pending", "select": "*", "order": "created_at.asc"})

    def set_job(self, job_id: str, status: str, **extra) -> None:
        values = {"status": status, **extra}
        self.update("jobs", {"id": f"eq.{job_id}"}, values)

    def count_posts(self, job_id: str) -> int:
        r = self._check(
            self.http.get("/posts", params={"job_id": f"eq.{job_id}", "select": "id"}, headers={"Prefer": "count=exact", "Range": "0-0"})
        )
        return int(r.headers["content-range"].split("/")[-1])


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
