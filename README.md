# Threads Analyzer

Threads 帳號貼文爬取與數據分析工具。

- 前端：Next.js（App Router、TypeScript、Tailwind），部署於 Vercel
- 登入與資料：Supabase（Auth + Postgres + RLS）
- 爬蟲：本機 Python CLI（`scripts/`），寫入 Supabase；前端只讀取

## 目錄結構

| 路徑 | 用途 |
|---|---|
| `src/` | Next.js 前端 |
| `scripts/` | Python 爬蟲／測試腳本 |
| `data/` | 爬取的原始資料、可行性測試輸出 |
| `reports/` | 產出的分析報告 |
| `supabase/migrations/` | 資料庫 schema 與 RLS |
| `docs/` | 文件（含 `feasibility.md` 可行性測試） |
| `AI_LOG.md` | AI 協作紀錄 |

## 本機開發

```bash
npm install
cp .env.example .env.local   # 填入 Supabase URL 與 anon key
npm run dev
```

## 環境變數

見 `.env.example`。`.env.local` 不可 commit。

## Python pipeline（`src/pipeline/`）

本機執行，用 **service_role key**（繞過 RLS）寫入 Supabase；key 只放 `.env`，不可進前端或 commit。

```bash
pip install -r requirements.txt
playwright install chromium     # 雲端沙箱已預裝 /opt/pw-browsers/chromium，會自動使用
cp .env.example .env            # 填入 SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY

python -m src.pipeline.run --pending        # 處理所有 pending 任務
python -m src.pipeline.run --job <job-id>   # 單一任務（可重跑，不會產生重複貼文）
```

爬蟲規則：不登入、不處理登入牆；每頁間隔 2–3 秒、逾時 30 秒、429/逾時指數退避重試 3 次。
未登入只拿得到個人頁首屏約 7–9 篇，詳見 `docs/feasibility.md`。Log 在 `logs/`。
