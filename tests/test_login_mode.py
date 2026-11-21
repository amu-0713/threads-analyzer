"""Login mode against a LOCAL fake Threads server (no real Threads, no real account).

Covers: storage_state is loaded, profile scrolling (limit / end of feed), per-post parsing, stopping on a dead session
or a verification screen, partial results kept, and src.pipeline.login saving only storage_state with mode 600.
Skipped when no Chromium is available.
"""

from __future__ import annotations

import json
import os
import re
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from src.pipeline import config
from src.pipeline.run import scrape_job
from src.pipeline.scraper import LoginInvalid, ScrapeError, ThreadsScraper, default_executable
from src.pipeline.usernames import normalize_username


class Fake(BaseHTTPRequestHandler):
    total = 60
    dead_code: str | None = None  # this post redirects to the login page (session died mid-run)
    challenge_code: str | None = None  # this post shows a verification screen
    log_lines: list[str] = []

    def log_message(self, *a):  # quiet
        pass

    def _send(self, body: str, status=200, headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        Fake.log_lines.append(path)
        if path == "/login":  # the page src.pipeline.login opens: "logging in" = a session cookie appears
            return self._send('<html><body>login<script>document.cookie="sessionid=ok; path=/"</script></body></html>')
        if path.startswith("/accounts/login"):
            return self._send("<html><body>Log in to continue</body></html>")
        if "sessionid=ok" not in (self.headers.get("Cookie") or ""):
            return self._redirect("/accounts/login/")
        m = re.match(r"^/@acct/post/(C\d+)$", path)
        if m:
            code = m.group(1)
            if code == Fake.dead_code:
                return self._redirect("/accounts/login/")
            if code == Fake.challenge_code:
                return self._send("<html><body>我們偵測到不尋常的活動，請確認這是你本人</body></html>")
            n = int(code[1:])
            post = {"code": code, "taken_at": 1795000000 + n * 3600, "caption": {"text": f"第 {n} 篇 內容 #測試"},
                    "like_count": n + 1, "user": {"username": "acct"},
                    "text_post_app_info": {"direct_reply_count": 1, "repost_count": 0, "quote_count": 0}}
            views = "1.2 萬次瀏覽" if n % 5 == 0 else f"{1000 + n} 次瀏覽"
            return self._send(f'<html><body>串文 {views}<time datetime="x">t</time>'
                              f'<script type="application/json">{json.dumps({"x": [post]})}</script></body></html>')
        if path == "/@acct":
            return self._send(
                "<html><body><div id=feed></div><script>"
                f"let n=0;const total={Fake.total};"
                "function more(){const f=document.getElementById('feed');for(let i=0;i<10&&n<total;i++,n++){"
                "const d=document.createElement('div');d.style.height='300px';"
                "d.innerHTML='<a href=\"/@acct/post/C'+n+'\">post</a><time>1</time>';f.appendChild(d);}}"
                "more();window.addEventListener('scroll',()=>{if(innerHeight+scrollY>=document.body.scrollHeight-400)more();});"
                "</script></body></html>")
        return self._send("not found", 404)


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(config, "MIN_DELAY_S", 0.05)
    monkeypatch.setattr(config, "MAX_DELAY_S", 0.1)
    monkeypatch.setattr(config, "SETTLE_S", 0.0)
    monkeypatch.setattr(config, "PAGE_TIMEOUT_MS", 8000)
    Fake.total, Fake.dead_code, Fake.challenge_code = 60, None, None


def _state(tmp_path: Path, base: str, cookie: bool = True) -> Path:
    p = tmp_path / "state.json"
    cookies = [{"name": "sessionid", "value": "ok", "domain": "127.0.0.1", "path": "/", "expires": -1,
                "httpOnly": False, "secure": False, "sameSite": "Lax"}] if cookie else []
    p.write_text(json.dumps({"cookies": cookies, "origins": []}))
    return p


def _scraper(tmp_path, base, **kw):
    try:
        s = ThreadsScraper(headless=True, executable_path=default_executable(), storage_state=_state(tmp_path, base, **kw), base_url=base)
        s.__enter__()
    except ScrapeError:
        raise
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Chromium available: {e}")
    return s


def test_delays_are_2_to_3_seconds_by_default():
    import importlib
    cfg = importlib.reload(config)
    assert (cfg.MIN_DELAY_S, cfg.MAX_DELAY_S, cfg.PAGE_TIMEOUT_MS, cfg.MAX_RETRIES, cfg.LOGIN_POST_LIMIT) == (2.0, 3.0, 30_000, 3, 40)


def test_scrolls_until_limit_and_parses_every_post(server, tmp_path):
    s = _scraper(tmp_path, server)
    try:
        profile = s.profile_posts_login("acct", limit=40)
        assert len(profile) == 40 and s.stats["scrolls"] >= 3
        sink: list[dict] = []
        recs = scrape_job(s, {"username": "acct", "mode": "login"}, sink)
        assert len(recs) == 40 and len(sink) == 40
        r = next(x for x in recs if x["code"] == "C0")
        assert r["views"] == 12000 and r["views_rounded"] is True and r["likes"] == 1 and "第 0 篇" in r["text"]
        r1 = next(x for x in recs if x["code"] == "C1")
        assert r1["views"] == 1001 and r1["views_rounded"] is False
    finally:
        s.__exit__(None, None, None)


def test_stops_at_end_of_feed(server, tmp_path):
    Fake.total = 25
    s = _scraper(tmp_path, server)
    try:
        assert len(s.profile_posts_login("acct", limit=40)) == 25
    finally:
        s.__exit__(None, None, None)


def test_session_without_cookie_stops_with_login_invalid(server, tmp_path):
    s = _scraper(tmp_path, server, cookie=False)
    try:
        with pytest.raises(LoginInvalid, match="登入"):
            s.profile_posts_login("acct")
    finally:
        s.__exit__(None, None, None)


def test_session_dies_midway_keeps_partial_records(server, tmp_path):
    Fake.total, Fake.dead_code = 12, "C3"
    s = _scraper(tmp_path, server)
    sink: list[dict] = []
    try:
        with pytest.raises(LoginInvalid):
            scrape_job(s, {"username": "acct", "mode": "login"}, sink)
        assert 0 < len(sink) < 12  # the posts fetched before the stop are still there
    finally:
        s.__exit__(None, None, None)


def test_verification_screen_stops_and_is_not_bypassed(server, tmp_path):
    Fake.total, Fake.challenge_code = 8, "C2"
    s = _scraper(tmp_path, server)
    try:
        with pytest.raises(LoginInvalid, match="驗證|不會嘗試繞過"):
            scrape_job(s, {"username": "acct", "mode": "login"}, [])
    finally:
        s.__exit__(None, None, None)


def test_missing_state_file_is_a_clear_error(tmp_path):
    with pytest.raises(ScrapeError, match="python -m src.pipeline.login"):
        ThreadsScraper(storage_state=tmp_path / "nope.json").__enter__()


def test_login_script_saves_only_storage_state_with_mode_600(server, tmp_path, monkeypatch):
    from src.pipeline import login
    monkeypatch.setattr(config, "THREADS_BASE", server)
    monkeypatch.setattr("builtins.input", lambda *a: "")  # "press Enter" (nobody types anything)
    out = tmp_path / ".secrets" / "threads_state.json"
    try:
        assert login.main(["--headless", "--state", str(out)]) == 0
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Chromium available: {e}")
    data = json.loads(out.read_text())
    assert set(data) == {"cookies", "origins"} and any(c["name"] == "sessionid" for c in data["cookies"])
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
    assert "password" not in out.read_text().lower()


def test_gitignore_covers_secrets():
    assert ".secrets/" in (Path(__file__).resolve().parents[1] / ".gitignore").read_text().splitlines()


def test_normalize_username_matches_the_web_rules():
    cases = {"7eleventw": "7eleventw", "@7ElevenTW": "7eleventw", "  @dcard.tw ": "dcard.tw",
             "https://www.threads.com/@7eleventw": "7eleventw", "https://www.threads.net/@Dcard.tw/post/ABC?xmt=1": "dcard.tw",
             "https://example.com/@foo": None, "bad name": None, "": None, "a" * 31: None}
    for raw, want in cases.items():
        assert normalize_username(raw) == want, raw


class FakeDb:
    """In-memory stand-in for src.pipeline.db.Db (only what run.py uses)."""

    def __init__(self):
        self.t = {"jobs": [], "posts": [], "job_summaries": [], "profiles": [{"id": "u1", "email": "me@example.com"}]}

    @staticmethod
    def _match(row, filters):
        for k, v in (filters or {}).items():
            if k in ("select", "order", "limit"):
                continue
            if v.startswith("eq."):
                if str(row.get(k)) != v[3:]:
                    return False
            elif v.startswith("not.in.("):
                if row.get(k) in [x.strip('"') for x in v[8:-1].split(",")]:
                    return False
        return True

    def select(self, table, params=None):
        return [dict(r) for r in self.t[table] if self._match(r, params)][: int((params or {}).get("limit", 10**6))]

    def insert(self, table, row):
        row = {"id": f"j{len(self.t[table]) + 1}", "status": "pending", "mode": "anonymous", **row}
        self.t[table].append(row)
        return dict(row)

    def upsert(self, table, rows, on_conflict):
        keys = on_conflict.split(",")
        for r in rows:
            old = next((x for x in self.t[table] if all(x.get(k) == r.get(k) for k in keys)), None)
            (old.update(r) if old else self.t[table].append(dict(r)))

    def update(self, table, filters, values):
        for r in self.t[table]:
            if self._match(r, filters):
                r.update(values)

    def delete(self, table, filters):
        self.t[table] = [r for r in self.t[table] if not self._match(r, filters)]

    def get_job(self, job_id):
        return next((dict(j) for j in self.t["jobs"] if j["id"] == job_id), None)

    def pending_jobs(self, mode=None):
        return [dict(j) for j in self.t["jobs"] if j["status"] == "pending" and (mode is None or j["mode"] == mode)]

    def set_job(self, job_id, status, **extra):
        self.update("jobs", {"id": f"eq.{job_id}"}, {"status": status, **extra})

    def count_posts(self, job_id):
        return sum(1 for p in self.t["posts"] if p["job_id"] == job_id)


def test_cli_login_add_runs_the_whole_pipeline(server, tmp_path, monkeypatch):
    from src.pipeline import run
    db = FakeDb()
    db.insert("jobs", {"user_id": "u1", "username": "acct", "mode": "anonymous"})  # an untouched anonymous job
    monkeypatch.setattr(run, "Db", lambda: db)
    monkeypatch.setattr(config, "THREADS_BASE", server)
    monkeypatch.setattr(run, "setup_logging", lambda: None)
    state = _state(tmp_path, server)
    try:
        rc = run.main(["--login", "--add", "@Acct", "--as", "me@example.com", "--state", str(state)])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Chromium available: {e}")
    assert rc == 0
    login_job = next(j for j in db.t["jobs"] if j["mode"] == "login")
    assert login_job["username"] == "acct" and login_job["status"] == "done" and login_job["post_count"] == 40
    assert len([p for p in db.t["posts"] if p["job_id"] == login_job["id"] and p["source"] == "real"]) == 40
    assert db.t["job_summaries"] and next(j for j in db.t["jobs"] if j["mode"] == "anonymous")["status"] == "pending"
    # wrong mode is refused; anonymous --pending never picks up login jobs
    assert run.main(["--job", login_job["id"]]) == 2
    assert [j["mode"] for j in db.pending_jobs("anonymous")] == ["anonymous"]


def test_cli_stops_the_whole_run_when_the_session_is_dead(server, tmp_path, monkeypatch):
    from src.pipeline import run
    db = FakeDb()
    monkeypatch.setattr(run, "Db", lambda: db)
    monkeypatch.setattr(config, "THREADS_BASE", server)
    monkeypatch.setattr(run, "setup_logging", lambda: None)
    state = _state(tmp_path, server, cookie=False)
    try:
        rc = run.main(["--login", "--add", "acct", "acct", "--as", "me@example.com", "--state", str(state)])
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Chromium available: {e}")
    assert rc == 3
    statuses = [j["status"] for j in db.t["jobs"]]
    assert statuses == ["failed", "pending"]  # stopped at the first job; the second one was not attempted
    assert "不會嘗試繞過" in db.t["jobs"][0]["error"]
