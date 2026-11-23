# Threads Analyzer

Threads 公開帳號的貼文爬取與數據分析工具：輸入帳號 → 本機爬蟲抓取貼文（未登入或登入模式）→ 分析 → 在網頁上看報告、比較帳號、匯出資料。

- **線上版**：https://threads-analyzer-ashen.vercel.app
- **前端**：Next.js 16（App Router、TypeScript、Tailwind、recharts），部署在 Vercel
- **登入與資料**：Supabase（Auth + Postgres + Row Level Security）
- **爬蟲與分析**：本機 Python CLI（`src/pipeline/`，Playwright），用 service_role key 寫入 Supabase；前端只讀取

## 展示帳號

demo 帳號請見交件信。

此帳號底下有 9 個分析任務：**未登入模式** 5 個（7eleventw、starbuckstw、dcard.tw、pchome24h，各自只有真實資料；以及補 mock 到 30 篇的 7eleventw 主分析任務），**登入模式** 4 個（上述 4 個帳號各 40 篇真實資料，洞察以這 4 個為主）。

## PRD 確認

PRD 已於 2026-11-21 經零一行銷確認。

## 功能

- Email／密碼註冊與登入（Supabase Auth；開啟 Confirm email 時，註冊後要先點信中連結）
- Dashboard：新增分析（輸入 `@帳號` 或個人頁網址，會正規化成 username，並選抓取模式）、任務列表（含模式）、重跑、刪除（有確認）
- 報告頁 `/dashboard/jobs/<id>`：總覽指標卡、互動率 Top 5、發文時段圖、文長 vs 互動率散佈圖、關鍵字與 hashtag、貼文類型、三組分類與代表貼文、「全部資料／僅真實資料」切換、mock 貼文明確標示、資料限制提示
- 匯出：CSV／JSON（含 `source` 欄位，標明 `real` 或 `mock`）
- 比較頁 `/dashboard/compare`：多個任務並列比較（只用真實資料，含模式欄；可把未登入與登入的同一帳號並排），並附 4 個帳號的洞察與內容建議（`reports/insights.md`，以登入模式 160 篇為主，未登入結果放附錄對照）
- 三組分類的「寫作清單」：每組綁一個行銷目標（共鳴型 → 擴大觸及、建立好感；討論型 → 帶動討論、收集意見；低迷型 → 要避開或改寫的寫法），列出該組貼文與其他貼文在字數（中位數）、提問句、含連結、晚間占比上的差別。**只列出前後期一致的寫法**（依發文時間分成前後兩半，方向相同、且兩半中該組都至少 3 篇）；真實貼文少於 20 篇時顯示「樣本太少，無法列出寫作清單」。分組規則本身沒有改
- AI 建議（選用）：先選目標（擴大觸及／帶動討論）與模型，Gemini 依該目標對應組別的穩定特徵產生 2–4 點可執行的做法（做法／依據／驗證）與一句「避開」，以卡片呈現並標明「AI 產生，僅供參考」與所用模型。結果依「目標＋模型」快取；切換時已有快取就直接顯示，沒有就即時產生，旁邊有「重新產生」。沒有 `LLM_API_KEY` 時按鈕停用
- 任務是 `pending` 時，列表與報告頁會顯示要在本機執行的指令與「複製」按鈕；`failed` 時顯示 `jobs.error`

## 目錄結構

| 路徑 | 用途 |
|---|---|
| `src/app`, `src/components`, `src/lib` | Next.js 前端（`src/proxy.ts` 負責保護 `/dashboard`） |
| `src/pipeline/` | Python：爬蟲、文字特徵、mock 生成、分析、CLI |
| `supabase/migrations/` | 資料表、RLS、權限 |
| `data/` | 可行性測試的原始輸出（`data/feasibility/`） |
| `reports/` | `insights.md`：洞察與內容建議 |
| `docs/` | `feasibility.md`（可行性）、`mock_design.md`（mock 設計與驗證）、`analysis.md`（分析輸出格式與分組） |
| `scripts/` | 可行性測試腳本（T1：個人頁、單篇頁、官方 API 文件查證） |
| `tests/` | 少量 pytest |
| `AI_LOG.md` | AI 協作紀錄 |

## 安裝

需求：Node.js 22+、Python 3.13、一個 Supabase 專案。

```bash
# 1. 前端
npm install

# 2. Python pipeline
pip install -r requirements.txt
playwright install chromium     # 雲端沙箱已預裝 /opt/pw-browsers/chromium，會自動使用
```

`jieba` 是 sdist，用最新的 setuptools 安裝可能出現 `install_layout` 錯誤；遇到時執行
`pip install "setuptools<70" wheel && pip install --no-build-isolation jieba`。

**資料庫**：依檔名順序把 `supabase/migrations/*.sql` 套用到你的 Supabase 專案（SQL Editor 貼上，或 `supabase db push`）。

**環境變數**（複製範本後填值，真實值不可 commit）：

```bash
cp .env.example .env.local   # 前端：NEXT_PUBLIC_SUPABASE_URL、NEXT_PUBLIC_SUPABASE_ANON_KEY（選用 LLM_API_KEY）
cp .env.example .env         # pipeline：SUPABASE_URL、SUPABASE_SERVICE_ROLE_KEY（預先產生 AI 建議另需 LLM_API_KEY）
```

`SUPABASE_SERVICE_ROLE_KEY` 會繞過 RLS，**只能放在本機 `.env`**，不可放進前端、Vercel 或 repo。

## 執行

### 前端

```bash
npm run dev      # http://localhost:3000
npm run build && npm start
```

### 爬蟲／分析 CLI

在 dashboard 新增分析後，任務是 `pending`；在本機執行：

```bash
python -m src.pipeline.run --pending                       # 處理所有 pending 任務
python -m src.pipeline.run --job <job-id>                  # 單一任務（可重跑，不會產生重複貼文）
python -m src.pipeline.run --job <job-id> --mock-to 30     # 真實篇數 < 30 時補 mock 到 30
python -m src.pipeline.run --job <job-id> --analyze-only   # 不重爬，只重跑分析
python -m src.pipeline.validate_mock --job <job-id>        # 分析能否找回 mock 內寫入的 3 個規律
python -m src.pipeline.advice --all --mode login            # 預先產生兩種目標的 AI 建議並存入 job_summaries.llm_advice（--job <id> 指定任務、--goal 擴大觸及|帶動討論、--model 白名單內的模型、--dry-run 只印不存）
python -m src.pipeline.insights_numbers --mode login       # 重現 reports/insights.md 引用的所有數字（--mode anonymous：附錄對照用的未登入資料）
python -m pytest -q tests
```

任務狀態：`pending → scraping → analyzing → done`（失敗為 `failed`，原因在 `jobs.error`）。在 dashboard 按「重跑」會把已完成或失敗的任務設回 `pending`，再執行 `--pending` 即可；原本有補 mock 的任務會沿用補到 30 篇。Log 寫在 `logs/`。

### 登入模式（用你自己的 Threads 帳號，在你自己的電腦上）

未登入只拿得到個人頁首屏（5–9 篇）。登入模式改用**你自己的登入工作階段**，個人頁可捲動到 40 篇：

```bash
python -m src.pipeline.login          # 開有畫面的 Chromium；你手動登入（含二階段驗證），回終端機按 Enter
python -m src.pipeline.run --login --add 7eleventw starbuckstw dcard.tw pchome24h --as <你的 dashboard email>   # 建立登入模式任務並執行（含分析）
python -m src.pipeline.advice --all --mode login                # 預先產生 AI 建議
python -m src.pipeline.insights_numbers --mode login            # 重現洞察引用的數字
```

- `login` 只儲存 Playwright 的 `storage_state`（cookies 與 local storage）到 `.secrets/threads_state.json`（已加入 `.gitignore`，檔案權限 600）。**程式不會要求、讀取或儲存帳號密碼。**
- `run --login` 載入該工作階段，個人頁捲動到 40 篇或到底為止，再逐篇開單篇頁取觀看數與互動數（解析方式與未登入相同）；每頁與每次捲動間隔 2–3 秒。
- **遇到登入失效、被導向登入頁、驗證或頻率限制畫面就停止並提示，不嘗試繞過**；已抓到的貼文會先存下，重跑時整批取代。
- 任務的模式存在 `jobs.mode`（`anonymous` / `login`）：`--login` 只處理登入模式的任務，不加 `--login` 只處理未登入任務；原本的未登入任務全部保留，作為對照。
- 失敗後重跑用 `--login --job <任務 id>`（不要再用 `--add`，會建出重複任務）；`--headed` 可以看到瀏覽器；`--limit N` 可改變捲動上限。
- 登入模式的流程用本機假伺服器測過（捲動、解析、登入失效、驗證畫面、保留部分結果）；實際登入後的頁面由使用者在自己電腦上執行驗證。

## 資料來源與合法性

本專案有兩種抓取模式，風險不同：

- **未登入模式（預設）**：用 Playwright 開啟公開的個人頁與單篇貼文頁，讀取頁面內嵌的 JSON（單篇頁的觀看數取自頁面標頭）。**不登入、不使用任何帳密或 cookie，不關閉、移除或繞過登入牆**（偵測到登入牆只記錄，不處理）。每頁間隔 2–3 秒、逾時 30 秒、遇 429／逾時以指數退避重試 3 次。
- **登入模式（出題方 2026-11-21 詢問「可以登入後抓取嗎」之後新增）**：使用**開發者自己的 Instagram／Threads 帳號**，在自己的電腦上登入，程式只保存登入工作階段（見上方「登入模式」）。風險控管：只用自己的帳號、低頻率（每頁與每次捲動 2–3 秒、每個帳號至多 40 篇）、**不存帳密**（只存工作階段檔，已 gitignore、權限 600，不上傳）、遇驗證或限制畫面立即停止、不使用任何反偵測手法；**用完請登出所有裝置並刪除 `.secrets/threads_state.json`**（Instagram／Threads 設定 → 帳號中心 → 密碼與安全性 → 登入的地點）。
- **兩種模式都仍屬條款灰色地帶**：Threads／Meta 的服務條款對自動化蒐集有限制，登入後以自動化方式存取更是如此，帳號有被限制或停權的風險（這是開發者自己的帳號，風險由開發者承擔）。本專案不主張這是「被允許」的，只是把風險降到最低，且僅用於分析展示。商業或大規模使用前應取得授權。
- **官方 API 無法完成本題目標**（2026-11-20 讀官方文件查證，細節在 `docs/feasibility.md` 第 7 節）：查詢任意公開帳號的貼文（`/profile_posts`）需要進階存取（App Review），且回傳欄位沒有任何互動數；互動數與觀看數只能由帳號擁有者透過 Insights 取得自己的貼文。
- **長期合法的方案**：向 Meta 申請 **Meta Content Library**（研究／機構用的官方資料管道）。這是我們認為合適的方向，但申請資格與可取得的欄位本專案沒有實際驗證。
- 未登入只拿得到個人頁首屏，真實貼文每個帳號只有 5–9 篇；為了展示分析流程，7eleventw 主分析任務用 **mock 資料**補到 30 篇（`posts.source='mock'`，全站都有標示，**洞察結論不使用**），設計與驗證見 `docs/mock_design.md`。登入模式的任務有 40 篇真實資料，不需要 mock。

## 指標定義

- **互動率** = (讚 + 回覆 + 轉發 + 引用) ÷ 觀看；**按讚率** = 讚 ÷ 觀看；**回覆率** = 回覆 ÷ 觀看
- 報告的指標：平均讚／回覆／轉發（另有中位數）、互動率 Top 5、發文時段分布（星期 × 時段，台北時間）、文長與互動關係（分箱 + Spearman）、常見關鍵字與 hashtag（jieba 斷詞，依含該詞的貼文數）、貼文類型分布
- **貼文類型**（每篇一個標籤，優先序：含連結 > 含 hashtag > 含 mention > 純文字）
- 晚間 = 台北時間 18:00–23:59；提問句 = 文字含 `？` 或 `?`（網址內的不算）
- 每項結果都有「全部資料」（真實 + mock）與「僅真實資料」兩版

## 三組分類規則

先把按讚率與回覆率轉成**帳號內百分位**（`(比它小的篇數 + 0.5 × 相等的篇數) ÷ n`；因為讚普遍大於回覆，直接相除不是標準化）：

1. 觀看 < 帳號觀看中位數的 20% → **未分組**（比率不可靠），也不參與百分位計算
2. **低迷型**：兩個百分位都 < 0.5
3. **討論型**：回覆百分位 ≥ 0.5 且 ≥ 按讚百分位
4. **共鳴型**：按讚百分位 ≥ 0.5 且 > 回覆百分位
5. 每組取最典型的 3–5 篇作為代表貼文，用同一套方法（關鍵字、類型、文長、提問／晚間／含連結比例）比較

完整輸出格式見 `docs/analysis.md`。

## 資料庫與安全

四張表：`profiles`、`jobs`、`posts`、`job_summaries`，全部啟用 RLS。未登入不可讀任何表；使用者只能建立、讀取、刪除自己的 `jobs`，並把已完成／失敗的任務改回 `pending`（只開放 `status`、`error`、`finished_at` 三欄）；`posts` 與 `job_summaries` 只能讀取（`job_summaries.llm_advice` 例外，擁有者可更新），一律經 `jobs.user_id` 判斷。寫入 `posts`／`job_summaries` 只由本機 pipeline 用 service_role key 進行。`jobs.mode`（`anonymous` / `login`）記錄抓取方式，RLS 不變。

## 部署（Vercel）

- Framework 自動偵測為 Next.js；`vercel.json` 把 Functions 區域設在東京（`hnd1`），與 Supabase（ap-northeast-1）同區。連到 GitHub `main`，push 後自動部署。
- **只需要兩個環境變數**（Production／Preview／Development 都設）：`NEXT_PUBLIC_SUPABASE_URL`、`NEXT_PUBLIC_SUPABASE_ANON_KEY`。
- 選用：`LLM_API_KEY`（Gemini API key，只在 server 端使用；改環境變數後需重新部署才生效）。**Preview 也要設**，否則分支預覽網址上的 AI 建議會停用。
- **不可**設定 service_role key。

## 已知限制

- **樣本有限**：未登入只拿得到個人頁首屏，每個帳號 5–9 篇；登入模式每個帳號 40 篇。兩者都不是「完整歷史」，也不是同一段時間（例如 7eleventw 的 40 篇只涵蓋 5 週，dcard.tw 涵蓋 5 個月），而且個人頁會夾帶舊的置頂貼文。百分位、分組與比較都只能當參考，**不能做統計推論**。
- **觀看數四捨五入**：單篇頁在觀看數 ≥ 1 萬時只顯示到千位（如「1.5 萬」），以 `views_rounded=true` 標記，介面以「≈」顯示，比率有些微誤差。觀看數取自 DOM（不是 JSON），頁面改版就會失效。
- **看不到素材**：只有文字，沒有圖片或影片資訊；轉發與引用在 JSON 可分開，DOM 只有合併值。
- **mock 不代表真實**：mock 只用來驗證分析管線；其中的規律是人為寫入的。
- **爬蟲在本機執行**：網頁只能新增任務與看結果，不能觸發爬取；dashboard 的「重跑」只是把任務設回 `pending`。
- **Supabase 的 leaked password protection 未啟用**：這項需要付費方案，目前的安全檢查會因此有一則警告。
- **註冊需要信箱驗證**（Confirm email 開啟）：Supabase 內建信件服務有寄信限制，展示請用上面的 demo 帳號。
- **AI 建議由 AI 產生，可能有誤**：Gemini 只看到「選定目標對應組別的穩定特徵」與篇數（不是原始貼文），報告頁已標明僅供參考。下拉只有兩個模型（白名單，server 端檢查，不接受任意模型名稱）：預設 `gemini-3.8-flash`（thinking 為 low；`minimal` 會被這個模型以 400 拒絕）與快速的 `gemini-3.1-flash-lite`（minimal，約 3–4 秒）。**這把 key 是免費額度：`gemini-3.8-flash` 每天只有 20 次請求**，用完後會顯示「每日請求額度已用完」，可改選快速模型或隔天再試；`gemini-3.8-flash` 另外常遇到 503（高需求），回應時間約 10–30 秒，超過原訂的 15 秒目標。回應不是合法 JSON、欄位缺漏或用了推論用語時會重試一次，仍失敗就顯示原因且不存檔。穩定度篩選只看方向，差距很小的特徵（例如 35 字 vs 38 字）也會通過。逐條檢查結果見 `reports/advice_acceptance.md`。
- **登入模式依賴使用者的工作階段**：工作階段過期、帳號被要求驗證或被限制時，爬取會停止；`storage_state` 檔等同登入狀態，必須自行妥善保管並在用完後刪除。
- **洞察裡的「邀請型／規則寫滿型」是人工分類**，在看過資料之後才判讀，屬於探索性分析（見 `reports/insights.md` 附錄 C）。
- 若 Threads 改版（頁面結構、內嵌 JSON、登入牆行為），爬蟲需要跟著調整。

## 未做項目

- **單元測試不完整**：目前只有少量 pytest（觀看數解析、文字特徵、mock 生成），前端沒有自動化測試、沒有 CI。
- **Docker**：沒有提供 Dockerfile／docker-compose。
- **官方 API 資料來源介面**：只在 `docs/feasibility.md` 評估，沒有實作；也沒有 Meta Content Library 的串接。
- **PRD 的「24 小時內同帳號不重抓」沒有實作**：同一帳號可以重複建立任務、重複爬取（目前只有每頁間隔 2–3 秒、逾時與重試等禮貌性限制）；也沒有針對同帳號的快取或頻率檢查。
- 排程自動爬取、以追蹤人數標準化的比較、多使用者共用任務。

## 開發紀錄

AI 協作過程（提問、AI 回應、發現的問題、最後決定）見 [`AI_LOG.md`](AI_LOG.md)。
