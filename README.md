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
