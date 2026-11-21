# Threads Analyzer

Threads 帳號貼文爬取與數據分析工具。

- 前端：Next.js（App Router、TypeScript、Tailwind），部署於 Vercel
- 登入與資料：Supabase（Auth + Postgres + RLS）
- 爬蟲：本機 Python CLI（`scripts/`），寫入 Supabase；前端只讀取

## 展示帳號

| 項目 | 值 |
|---|---|
| Email | `demo@threads-analyzer.dev` |
| 密碼 | `Demo-2026!` |

此帳號底下已有 5 個分析任務（7eleventw、starbuckstw、dcard.tw、pchome24h，以及補 mock 到 30 篇的 7eleventw 主分析任務）。
（repo 為 private；正式公開前請移除或更換這組帳密。）

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
python -m src.pipeline.run --job <job-id> --mock-to 30   # 真實篇數 < 30 時補 mock 到 30（docs/mock_design.md）
python -m src.pipeline.run --job <job-id> --analyze-only # 不重爬，只重跑分析
python -m src.pipeline.validate_mock --job <job-id>      # 分析能否找回 mock 的 3 個規律
```

爬蟲規則：不登入、不處理登入牆；每頁間隔 2–3 秒、逾時 30 秒、429/逾時指數退避重試 3 次。
未登入只拿得到個人頁首屏約 7–9 篇，詳見 `docs/feasibility.md`。Log 在 `logs/`。

在 dashboard 按「重跑」會把任務設回 `pending`，之後在本機執行 `--pending` 即可（原本有補 mock 的任務會沿用補到 30 篇）。

分析輸出格式與分組規則見 `docs/analysis.md`。任務流程：`pending → scraping → analyzing → done`（失敗為 `failed`，原因寫在 `jobs.error`）。

## 部署（Vercel）

- Framework：Next.js（自動偵測）；`vercel.json` 把 Functions 區域設在東京（`hnd1`），與 Supabase（ap-northeast-1）同區。
- **只需要兩個環境變數**（Production / Preview / Development 都設）：
  `NEXT_PUBLIC_SUPABASE_URL`、`NEXT_PUBLIC_SUPABASE_ANON_KEY`。
- 選用：`LLM_API_KEY`（Gemini API key，只在 server 端使用）。沒設定時，報告頁的「產生 AI 建議」按鈕會停用。
- **不可**設定 service_role key：前端只用 anon key + RLS 讀寫；service_role 只給本機 Python pipeline。
