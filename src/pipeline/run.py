"""Pipeline CLI.

    python -m src.pipeline.run --pending            # every pending ANONYMOUS job
    python -m src.pipeline.run --job <job-id>       # one job (re-runnable)

Login mode (your own Threads session saved by `python -m src.pipeline.login`):
    python -m src.pipeline.run --login --pending                       # every pending LOGIN-mode job
    python -m src.pipeline.run --login --job <job-id>
    python -m src.pipeline.run --login --add 7eleventw dcard.tw --as you@example.com   # create login-mode jobs, then run them

A job's mode (anonymous / login) is stored in jobs.mode; --login only touches login-mode jobs and the
default only touches anonymous ones. Reads/writes Supabase with the service_role key from .env. Logs go to logs/.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from . import config
from .db import Db, now_iso
from .analysis import analyze
from .features import text_features
from .mock import generate_mock
from .scraper import LoginInvalid, ScrapeError, ThreadsScraper, to_taipei_iso
from .usernames import normalize_username

log = logging.getLogger("pipeline")

# Fields we report coverage for after each scrape.
COVERAGE_FIELDS = ["posted_at", "text", "views", "likes", "replies", "reposts", "quotes", "post_url"]


def setup_logging() -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is just noise
    for h in (
        logging.FileHandler(config.LOG_DIR / f"pipeline-{datetime.now():%Y%m%d}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ):
        h.setFormatter(fmt)
        root.addHandler(h)


def build_post_row(job_id: str, rec: dict) -> dict:
    text = rec.get("text") or ""
    return {
        "job_id": job_id,
        "post_url": rec["post_url"],
        "posted_at": to_taipei_iso(rec.get("taken_at")),
        "text": text,
        "views": rec.get("views"),
        "views_rounded": bool(rec.get("views_rounded")),
        "likes": rec.get("likes") or 0,
        "replies": rec.get("replies") or 0,
        "reposts": rec.get("reposts") or 0,
        "quotes": rec.get("quotes") or 0,
        **text_features(text),
        "source": "real",
    }


def coverage(rows: list[dict]) -> dict:
    n = len(rows)
    return {
        f: {"count": sum(1 for r in rows if r.get(f) not in (None, "")), "total": n,
            "pct": round(100 * sum(1 for r in rows if r.get(f) not in (None, "")) / n, 1) if n else 0.0}
        for f in COVERAGE_FIELDS
    }


def scrape_job(scraper: ThreadsScraper, job: dict, sink: list[dict] | None = None) -> list[dict]:
    """Scrape one job. Records are appended to `sink` as they come, so a stop half-way (LoginInvalid) keeps them."""
    username = job["username"]
    login = scraper.login_mode
    profile = scraper.profile_posts_login(username) if login else scraper.profile_posts(username)
    if not profile:
        raise ScrapeError(f"no posts found for @{username} (account missing/private, or login wall)")
    records = sink if sink is not None else []
    for i, (code, prof_rec) in enumerate(sorted(profile.items(), key=lambda kv: -(kv[1].get("taken_at") or 0)), 1):
        try:
            rec = scraper.post_page(username, code, fallback=prof_rec)
        except LoginInvalid:
            raise  # session dead / verification screen: stop everything
        except ScrapeError as e:
            if login:  # one unreadable post must not cost the other 39
                log.warning("[%d/%d] %s skipped: %s", i, len(profile), code, e)
                continue
            raise
        log.info("[%d/%d] %s likes=%s replies=%s views=%s%s", i, len(profile), code, rec.get("likes"),
                 rec.get("replies"), rec.get("views"), "~" if rec.get("views_rounded") else "")
        records.append(rec)
    return records


def run_analysis(db: Db, job_id: str) -> None:
    """Read the job's posts, compute the summary, write job_summaries and posts.group."""
    posts = db.select("posts", {"job_id": f"eq.{job_id}", "select": "*", "order": "posted_at.desc"})
    if not posts:
        raise RuntimeError("no posts to analyze")
    res = analyze(posts)
    db.upsert("job_summaries", [{
        "job_id": job_id,
        "metrics": res["metrics"],
        "top_posts": res["top_posts"],
        "group_analysis": res["group_analysis"],
        "insights": res["insights"],
        "updated_at": now_iso(),
    }], on_conflict="job_id")
    for url, group in res["post_groups"].items():
        db.update("posts", {"job_id": f"eq.{job_id}", "post_url": f"eq.{url}"}, {"group": group})
    counts = res["group_analysis"]["all"]["counts"]
    log.info("analysis written: %d posts, groups %s", len(posts), counts)


def save_real(db: Db, job: dict, rows: list[dict], scraper: ThreadsScraper, partial: bool = False) -> None:
    job_id = job["id"]
    db.delete("posts", {"job_id": f"eq.{job_id}", "source": "eq.mock"})  # reruns start from real data only
    db.upsert("posts", rows, on_conflict="job_id,post_url")
    if not partial:
        # a rerun replaces the real set: drop real rows that no longer show up
        keep = ",".join(f'"{r["post_url"]}"' for r in rows)
        db.delete("posts", {"job_id": f"eq.{job_id}", "source": "eq.real", "post_url": f"not.in.({keep})"})
    cov = coverage(rows)
    (config.LOG_DIR / f"job_{job_id}_coverage.json").write_text(
        json.dumps({"username": job["username"], "mode": job.get("mode", "anonymous"), "partial": partial, "real_posts": len(rows),
                    "coverage": cov, "scraper": scraper.stats}, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("%s %d real posts; coverage %s", "saved PARTIAL" if partial else "scraped", len(rows),
             {k: f"{v['pct']}%" for k, v in cov.items()})


def scrape_stage(db: Db, scraper: ThreadsScraper, job: dict, mock_to: int) -> None:
    job_id, username = job["id"], job["username"]
    if not mock_to and db.select("posts", {"job_id": f"eq.{job_id}", "source": "eq.mock", "select": "id", "limit": "1"}):
        mock_to = config.MOCK_TARGET  # a rerun (e.g. from the dashboard) keeps the job's mock top-up
        log.info("job had mock posts before; keeping the top-up to %d", mock_to)
    records: list[dict] = []
    try:
        scrape_job(scraper, job, records)
    except LoginInvalid as e:
        if records:  # keep the work already done; a rerun replaces it
            save_real(db, job, [build_post_row(job_id, r) for r in records], scraper, partial=True)
            raise LoginInvalid(f"{e}（已先存 {len(records)} 篇；重跑會整批取代）") from e
        raise
    rows = [build_post_row(job_id, r) for r in records]
    save_real(db, job, rows, scraper)
    if mock_to and len(rows) < mock_to:
        mock_rows = generate_mock(job_id, username, rows, target=mock_to)
        db.upsert("posts", mock_rows, on_conflict="job_id,post_url")
        log.info("added %d mock posts (real %d + mock %d = %d)", len(mock_rows), len(rows), len(mock_rows), mock_to)


def process_job(db: Db, scraper: ThreadsScraper | None, job: dict, mock_to: int = 0) -> None:
    """pending -> scraping -> analyzing -> done (or failed). scraper=None re-runs only the analysis."""
    job_id = job["id"]
    log.info("=== job %s @%s ===", job_id, job["username"])
    t0 = time.time()
    try:
        if scraper is not None:
            db.set_job(job_id, "scraping", error=None, finished_at=None)
            scrape_stage(db, scraper, job, mock_to)
        db.set_job(job_id, "analyzing", error=None, finished_at=None)
        run_analysis(db, job_id)
        db.set_job(job_id, "done", post_count=db.count_posts(job_id), finished_at=now_iso(), error=None)
    except LoginInvalid as e:  # session dead / verification screen: mark the job, then stop the whole run
        log.error("job %s stopped: %s", job_id, e)
        db.set_job(job_id, "failed", error=str(e)[:500], finished_at=now_iso())
        raise
    except Exception as e:  # noqa: BLE001 - any failure must end up on the job row
        log.exception("job %s failed", job_id)
        db.set_job(job_id, "failed", error=str(e)[:500], finished_at=now_iso())
    log.info("job %s finished in %.0fs", job_id, time.time() - t0)


def add_jobs(db: Db, usernames: list[str], email: str, mode: str) -> list[dict]:
    users = db.select("profiles", {"email": f"eq.{email}", "select": "id"})
    if not users:
        raise SystemExit(f"找不到 dashboard 帳號 {email}（要用你在 dashboard 登入的那個 email）。")
    jobs = []
    for raw in usernames:
        name = normalize_username(raw)
        if not name:
            raise SystemExit(f"無效的 Threads 帳號：{raw!r}")
        job = db.insert("jobs", {"user_id": users[0]["id"], "username": name, "mode": mode})
        log.info("created %s job %s for @%s", mode, job["id"], name)
        jobs.append(job)
    return jobs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.pipeline.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pending", action="store_true", help="process every pending job of the selected mode")
    g.add_argument("--job", metavar="ID", action="append", help="process a job by id (repeatable)")
    g.add_argument("--add", nargs="+", metavar="USERNAME", help="create jobs (mode follows --login) and process them; needs --as")
    ap.add_argument("--as", dest="as_email", metavar="EMAIL", help="dashboard account that will own the jobs created by --add")
    ap.add_argument("--login", action="store_true", help="login mode: use the saved Threads session (python -m src.pipeline.login)")
    ap.add_argument("--state", type=Path, default=config.STATE_PATH, help=f"login session file (default {config.STATE_PATH})")
    ap.add_argument("--limit", type=int, default=config.LOGIN_POST_LIMIT, metavar="N", help="login mode: scroll until N posts (default %(default)s)")
    ap.add_argument("--mock-to", type=int, default=0, metavar="N",
                    help="if fewer than N real posts were scraped, top up with source='mock' rows (default: off)")
    ap.add_argument("--analyze-only", action="store_true", help="skip scraping; re-run the analysis on posts already in the DB")
    ap.add_argument("--headed", action="store_true", help="show the browser window (default: headless)")
    args = ap.parse_args(argv)
    if args.add and not args.as_email:
        ap.error("--add needs --as <your dashboard email>")
    setup_logging()
    config.LOGIN_POST_LIMIT = args.limit
    mode = "login" if args.login else "anonymous"

    db = Db()
    if args.add:
        jobs = add_jobs(db, args.add, args.as_email, mode)
    elif args.job:
        jobs = []
        for job_id in args.job:
            job = db.get_job(job_id)
            if not job:
                log.error("job %s not found", job_id)
                return 2
            if not args.analyze_only and job.get("mode", "anonymous") != mode:
                log.error("job %s is %s mode; %s", job_id, job.get("mode"), "add --login" if job.get("mode") == "login" else "drop --login")
                return 2
            jobs.append(job)
    else:
        jobs = db.pending_jobs(mode)
    if not jobs:
        log.info("nothing to do (%s mode)", mode)
        return 0

    if args.analyze_only:
        for job in jobs:
            process_job(db, None, job)
        return 0
    try:
        with ThreadsScraper(headless=not args.headed, storage_state=args.state if args.login else None) as scraper:
            for job in jobs:
                process_job(db, scraper, job, mock_to=args.mock_to)
    except LoginInvalid as e:
        log.error("%s", e)
        return 3
    except ScrapeError as e:  # e.g. missing login state file
        log.error("%s", e)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
