# AI 協作紀錄

本專案全程使用 Claude 協助：**PRD 階段**在 Claude 對話中討論需求與可行性；**開發階段**用 Claude Code 實作 T1–T14。
下面依題目要求分五節。每一節內再依時間分成「PRD 階段」與「開發階段」，每筆紀錄固定四個欄位：**我的提問／AI 回應／發現的問題／最後決定**。

> 說明：
> - 「我」是開發者；開發階段的「我的提問」是我給 Claude Code 的任務指示（摘要）。
> - **PRD 階段**是依我自己整理的對話重點寫成，**不是逐字紀錄**；AI 回應欄只寫我能確定的部分。開發階段則依 `git log`、`docs/` 與實作當下的紀錄整理。
> - commit 編號（如 `7a4c784`）可用 `git show` 對照。

## 一、如何向 AI 描述需求

### PRD 階段（Claude 對話）

**P1　要求區分「照題目」與「AI 自訂」**
- 我的提問：PRD 裡哪些內容是題目明寫的要求，哪些是 AI 自己加的？請分開標示。
- AI 回應：重新整理，把兩類內容分開標示。
- 發現的問題：分開之後才發現 **AI 漏寫了題目要求的 6 個必產出指標**；沒有這個要求，缺漏會被 AI 自訂的內容蓋過去。
- 最後決定：把題目要求的指標補回 PRD。開發時 T6 的指標清單就是這 6 類：平均讚／回覆／轉發、互動率 Top 5、發文時段分布、文長與互動關係、關鍵字與 hashtag、貼文類型分布，報告頁（T7）逐項呈現。

**P2　做分組之前，先問「這三組要回答什麼問題」**
- 我的提問：在決定怎麼分組前，這個分組要幫使用者回答什麼問題？
- AI 回應：提出兩個方案：①依表現高／中／低分層；②依互動型態分組。
- 發現的問題：高中低分層只回答「誰比較好」，沒有告訴使用者「為什麼」或「下一步怎麼做」。
- 最後決定：選「互動型態」，分成低迷型／討論型／共鳴型（規則見 `docs/analysis.md`）。

**P3　提出用觀看數標準化**
- 我的提問：互動數會被曝光量帶著跑，是否應該除以觀看數？
- AI 回應：同意；另外提出「觸及率」這類指標。
- 發現的問題：觸及率不在題目要求內，會偏離題目。
- 最後決定：互動比率以觀看數為分母；觸及率不當主要指標，只當解釋變數。

**P4　資料策略：否決登入爬取與純 mock**
- 我的提問：未登入只能抓到約 7–9 篇，要怎麼辦？
- AI 回應：列出可行方案（可行性文件第 6 節的 A–D），其中包括登入後捲動爬取，以及全部用 mock 資料。
- 發現的問題：登入爬取違反條款與題目限制；純 mock 沒有任何真實資料，洞察就沒有根據。
- 最後決定：**兩者都否決**。採「單一帳號：真實 + mock 驗證分析管線；多個帳號：只用真實資料做洞察」。這個決定後來決定了 T5b 的 mock 設計，以及 T9 洞察絕不使用 mock。

### 開發階段（Claude Code）

**D1　用 checkpoint + 限制 + 驗收來描述任務**
- 我的提問：每次任務都寫成「角色 / 背景 / 分幾個 checkpoint（各自 commit）/ 限制 / 驗收 / 完成後 5 行總結」。例如 T2–T4 的限制是「只做這三項，不要提前做爬蟲」「不可 commit 金鑰」，驗收是「未登入開 /dashboard 會被導回 /login」「用兩個帳號測試，A 看不到 B 的任務」。
- AI 回應：照 checkpoint 逐一實作並 commit（`96f4a2f`、`e2cef20`、`2498a92`），驗收條件寫成實際的 e2e 測試。
- 發現的問題：驗收條件寫得越具體，測試越有意義（「A 看不到 B」直接變成兩個帳號的 Playwright 測試與 SQL 層 RLS 測試）。
- 最後決定：之後每個階段都沿用這個格式。

**D2　把「要不要動外部資源」的決定留給我**
- 我的提問：先向我索取 Supabase 金鑰；後來改成「用 MCP 新建專案 `threads-analyzer`，不要使用既有專案，免費額度不夠就先停下來告訴我」。
- AI 回應：先查組織方案與既有專案數（免費方案、只有 1 個專案），確認額度夠才建立；取得 URL 與 anon key 後寫入 `.env.local`（已 gitignore）。
- 發現的問題：無。
- 最後決定：涉及建立／刪除外部資源（Supabase 專案、Vercel 專案、放行網域、金鑰）一律先問或先寫明限制。

**D3　測試受阻時，要求提出替代方案而不是動 secret**
- 我的提問：沙箱注入的 apikey 會干擾使用者登入；e2e 若受影響，請提出不依賴刪除 secret 的解法，不要自行刪除。
- AI 回應：改在**部署網址**上跑 e2e（見 3 節）；本機能做的只做畫面預覽；沒有動任何 secret。
- 發現的問題：這代表 T4 以後的使用者流程只能在部署後完整驗證。
- 最後決定：接受；並在總結裡如實說明哪些在沙箱驗證、哪些在部署網址驗證。

## 二、AI 產生了哪些程式碼

**全部程式碼都由 Claude Code 撰寫**；我負責需求、限制、驗收與決策。目前 repo 的規模（`git ls-files`）：Python `src/pipeline/` 約 1,230 行、前端（`src/app`、`components`、`lib`）約 1,400 行、migration 約 180 行、可行性腳本約 820 行、文件約 620 行。

| 階段 | 內容 | 主要檔案 |
|---|---|---|
| T1（可行性，11/20） | 未登入個人頁測試、單篇頁測試、官方 API 文件查證 | `scripts/*.py`、`docs/feasibility.md`、`data/feasibility/` |
| T2 | Next.js 骨架與題目要求的目錄 | `package.json`、`src/`、`vercel.json` |
| T3 | 4 張表 + RLS + 權限 | `supabase/migrations/20261121000000_init_schema.sql` |
| T4 | Email／密碼登入、保護 `/dashboard`、任務列表與新增表單、username 正規化 | `src/proxy.ts`、`src/app/login`、`src/app/dashboard`、`src/lib/username.ts` |
| T5 | 爬蟲 CLI、文字特徵、PostgREST client | `src/pipeline/scraper.py`、`run.py`、`features.py`、`db.py` |
| T5b | mock 生成器（含 3 個已知規律）與設計文件 | `src/pipeline/mock.py`、`docs/mock_design.md` |
| T6 | 分析、分組、驗證腳本 | `src/pipeline/analysis.py`、`validate_mock.py`、`docs/analysis.md` |
| T7 | 報告頁與 recharts 圖表 | `src/app/dashboard/jobs/[id]`、`src/components/report`、`charts` |
| T14 | 多帳號比較頁 | `src/app/dashboard/compare` |
| T10 | Vercel 專案、環境變數、部署 | `vercel.json`、Vercel 專案設定 |
| T11 | CSV／JSON 匯出 | `src/app/dashboard/jobs/[id]/export`、`src/lib/export.ts` |
| T13 | 重跑／刪除、對應的 RLS migration | `src/app/dashboard/actions.ts`、`20261121010000_jobs_rerun.sql` |
| T12 | Gemini 建議 | `src/lib/llm.ts`、`20261121020000_llm_advice.sql` |
| T9 | 洞察、數字重現腳本、比較頁顯示 | `reports/insights.md`、`src/pipeline/insights_numbers.py` |
| 文件 | README、本檔 | `README.md`、`AI_LOG.md` |

## 三、如何驗證正確性

### PRD 階段（Claude 對話）

**V-P1　追問「團隊確認後才能開發」的原文出處**
- 我的提問：「需團隊確認後才能開發」是題目原文嗎？出處在哪裡？
- AI 回應：PRD 中出現這項要求（由我追問出處）。
- 發現的問題：不確定它是題目規定還是 AI 加上去的流程。
- 最後決定：**核對出處、確認之後才採用**；不確定的要求不放進 PRD。

**V-P2　追問「爬蟲不登入」是不是 AI 自己設計的**
- 我的提問：「不登入」是 AI 自行設計的限制，還是有依據？
- AI 回應：說明了不登入的合規理由。
- 發現的問題：無；理由與後來 `docs/feasibility.md` 第 6 節的評估一致（登入後爬取違反服務條款與題目限制，也有封號風險）。
- 最後決定：確認合規理由後保留「不登入、不繞過登入牆」，後來寫進 README 的「資料來源與合法性」。

**V-P3　PRD 定稿後送交確認**
- 我的提問：PRD 定稿後，依 V-P1 確認的流程要求，交由零一行銷確認後才開始正式開發。
- AI 回應：（這是人工確認流程，不是 AI 產出。）
- 發現的問題：無。
- 最後決定：**PRD 於 2026-11-21 經零一行銷確認**，之後開始開發階段（T2 起）。

### 開發階段（Claude Code）

| 驗證項目 | 做法 | 結果 |
|---|---|---|
| RLS（T3） | 在資料庫內模擬兩個使用者：匿名讀、讀別人的 jobs、替別人建 job、寫 posts、改別人的資料 | 全部被拒；測完 rollback；每次 migration 後跑 Supabase 安全檢查（只剩 leaked password protection 一則，屬付費功能） |
| RLS（T13、T12） | 同上，驗證 `jobs` 只能「done/failed → pending」、不能改其他欄位、`llm_advice` 只能改自己的 | 符合預期 |
| 登入與隔離（T4） | Playwright：未登入 → 導回 /login、錯誤密碼、兩個帳號互看不到對方 | 通過 |
| 爬蟲 | 抽查 DB 內容；同一任務重跑兩次，貼文數維持 8（不重複）；覆蓋率寫在 `logs/job_*_coverage.json` | 通過 |
| 觀看數位置 | 先用探測腳本確認「N 次瀏覽」在串文第 1 篇與第 2 篇的單篇頁數字不同（3.0 萬 vs 1 萬），再決定用頁首文字當該篇觀看數 | 合理推論（Threads 沒有明文標示） |
| mock 驗證（T5b、T6） | `validate_mock` 用與 pipeline 相同的檢定，比較「全部／僅 mock／僅真實」三種範圍是否找回 3 個規律 | 全部／僅 mock 都找回；僅真實樣本不足（結果與修正過程見 `docs/mock_design.md`） |
| 前端（T7、T14） | 用資料庫匯出的資料做暫時預覽頁看桌機與 390 寬手機；上線後在部署網址再跑一次 | 通過 |
| 部署後 e2e（T10–T13） | 在部署網址用 Playwright：demo 登入、報告頁圖表與 mock 標示、「僅真實」切換、匯出（CSV 30 列含 22 列 mock、僅真實 8 列）、比較頁、新增後刪除（含確認視窗）、重跑、第二個帳號看不到 demo 的任務且報告／匯出回 404、登出後被擋 | 通過；其中 2 項計數當下不準，以資料庫確認（見四、D-4） |
| 洞察（T9） | 所有數字由 `python -m src.pipeline.insights_numbers` 從資料庫重算；文件寫完後逐項對照原貼文全文與數字 | 發現 3 處說法不準並修正（見四、D-7） |
| Gemini（T12） | 先用 stub 驗證請求格式、錯誤與截斷處理；部署後用真實金鑰在部署網址實測 | 見四、D-8 |
| 靜態檢查 | `tsc`、`eslint`、`next build`；少量 pytest（觀看數解析、文字特徵、mock 生成與 3 個規律的方向） | 通過 |

## 四、修正了哪些錯誤或幻覺

### PRD 階段（Claude 對話）

**E-P1　AI 把「讚 ÷ 回覆」當成標準化**
- 我的提問：讚普遍遠大於回覆，兩者直接相除（或用同一個門檻）算不算標準化？
- AI 回應：承認原本的規則有**量級問題**（讚的量級大，會主導結果）。
- 發現的問題：原規則在量級不同的指標之間比較，結果只反映「哪個數字比較大」。
- 最後決定：改成**帳號內百分位排名**：先把按讚率與回覆率各自轉成百分位，再依兩者的相對位置分組（T6 實作）。

**E-P2　官方 API 的設定步驟是憑記憶寫的**
- 我的提問：官方 Threads API 要怎麼申請與設定？
- AI 回應：第一版給了步驟。
- 發現的問題：**步驟是 AI 憑記憶寫的，與實際畫面對不上**。
- 最後決定：改為直接讀 Meta 官方文件再寫，並在 `docs/feasibility.md` 第 7 節逐項標註「文件明確寫出」或「文件沒寫、未確認」，沒有實測的部分也明說。

（另見一、P1：AI 漏寫 6 個必產出指標。）

### 開發階段（Claude Code）

**D-1　缺值被默默寫成 0（T5，`0fc2a22`）**
- 我的提問：（T5 任務）解析時間、文字、讚、回覆、轉發、引用、觀看，upsert 到 posts。
- AI 回應：第一版爬蟲 `rec.get("likes") or 0`，把缺值寫成 0，coverage 還因此顯示讚數 100%。
- 發現的問題：starbuckstw 有 2 篇的 log 顯示 `likes=None replies=None views=None`、發文時間覆蓋率只有 71.4%；追查發現它們的單篇頁會被導回首頁（貼文已不存在），個人頁 JSON 只有殘缺的殼。
- 最後決定：不完整（沒有時間或讚數）的貼文不寫入；重跑時同步刪除不再出現的舊真實資料。starbuckstw 從 7 篇修正為 5 篇，重跑後以資料庫確認。

**D-2　mock 抽樣不平衡，改為固定篇數；倍率沒動（T5b／T6，`f6a4c8a`）**
- 我的提問：分析能不能找回 mock 裡寫入的 3 個規律？
- AI 回應：第一次驗證，三個方向都對，但只有提問句顯著；晚間 p = 0.29、含連結 p = 0.059。
- 發現的問題：22 篇 mock 裡逐篇擲骰剛好只抽到 4 篇晚間貼文（預期約 8 篇），對照組太不平衡。這是「樣本配置運氣」，不是檢定方法的問題。
- 最後決定：**只改一處**——特徵分配改成固定各特徵篇數再洗牌（平衡設計）；倍率（3／2／0.4）、雜訊、檢定方法都沒動。修改前後的結果都寫進 `docs/mock_design.md`，並註明這是唯一一次依驗證結果修改 mock。重新驗證後 3 個規律在「全部」與「僅 mock」都找回（p 約 0.002–0.02）。

**D-3　anon key 手打錯誤，改由檔案讀取（T10）**
- 我的提問：只設兩個環境變數到 Vercel。
- AI 回應：建立專案時把 anon key 直接打進工具呼叫。
- 發現的問題：**金鑰尾端是憑記憶打的，是錯的**（不是從 `.env.local` 複製）。AI 在建完專案後自己發現。
- 最後決定：從 `.env.local` 讀出正確值，解開 JWT 確認 `ref` 是這個 Supabase 專案，再用 upsert 覆蓋，並列出專案環境變數確認；錯誤值沒有被任何部署使用（部署在修正之後）。之後涉及金鑰一律從檔案讀取。

**D-4　測試腳本計數不準，改查資料庫確認（T13）**
- 我的提問：（驗收）新增後可刪除、重跑會把狀態設回 pending。
- AI 回應：部署網址 e2e 印出「刪除後仍有 1 筆」「重跑後 starbuckstw 仍是 done」。
- 發現的問題：訊息卻顯示「已刪除任務」，數字互相矛盾；原因是腳本等 server action 的時間不夠，讀到的是上一個畫面。
- 最後決定：**不下結論，直接查資料庫**：`tmp_e2e` 已刪除、`starbuckstw` 已是 pending。之後再用 CLI 把它處理回 done（驗證整個重跑流程）。

**D-5　Next.js 16：查文件，不憑記憶（T4）**
- 我的提問：middleware 保護 /dashboard，未登入導回 /login。
- AI 回應：`AGENTS.md` 提醒這版有破壞性變更，AI 沒有照舊習慣直接寫 `middleware.ts`，而是先讀 `node_modules/next/dist/docs/`（`proxy.md`、`version-16.md`）。
- 發現的問題：16 版把 `middleware` 改名為 `proxy`（執行環境也變成 Node.js）；scaffold 預設還開了 `cacheComponents`，build 直接報錯。
- 最後決定：檔案用 `src/proxy.ts`、匯出 `proxy`；關掉 `cacheComponents` 與 `partialPrefetching`（本專案以 cookie 認證，所有頁面都是動態的）。

**D-6　service_role 金鑰型態與沙箱注入（T5）**
- 我的提問：用 service_role key 寫入，key 只放 `.env`。
- AI 回應：先以 `Authorization: Bearer` 設定金鑰，請求回 401：`Expected 3 parts in JWT`。
- 發現的問題：我提供的是新式 `sb_secret_` 金鑰，不是 JWT，只能放在 `apikey` header。
- 最後決定：改用 `apikey` header 重設；`db.py` 判斷金鑰型態（JWT 才多送 `Authorization`）。另外發現這把金鑰被 proxy 套到**所有**對該 host 的請求，連使用者登入都被蓋掉，所以 5 個任務改用 service client 以 demo 帳號的 `user_id` 建立（不是從 dashboard 點出來的），並在總結裡明說；使用者流程改在部署網址驗證（見 D3）。

**D-7　洞察初稿有 3 處說法不準（T9）**
- 我的提問：洞察至少 3 點，每點要分「觀察」與「推測」，不可用 mock。
- AI 回應：初稿依資料寫完。
- 發現的問題：寫完後對照原文與數字重新核對，抓到三處：①把 LNGSHOT 抽獎當成「低門檻一句話參加」，但讀全文發現它的規則（追蹤、按讚轉發、@朋友）不簡單，改成以「首篇長短」為主要觀察，並寫出這個反證；②「dcard.tw 7 篇都是導流型」不對（只有 2 篇明寫「搜尋文章標題」，另有 1 篇純圖、1 篇是 6 月聲明）；③「抽獎以外按讚率最高的兩篇都是極短文」不對（第 3 高 4.38% 是 200 字的公告），改為「前 5 名裡有 2 篇」並把反例寫進去。
- 最後決定：所有數字改由 `insights_numbers.py` 產出；文件中明寫反證、混淆因素與樣本限制。

**D-8　Gemini：模型名稱過時、輸出被截斷（T12）**
- 我的提問：Gemini API，沒有 key 時按鈕停用；建議要標明 AI 產生。
- AI 回應：預設模型用 `gemini-2.5-flash`；沙箱的 credential 機制不支援 `x-goog-api-key` header，所以第一版只能用 stub 驗證。
- 發現的問題：部署後第一次實測就失敗：①該模型已不開放新使用者（**預設模型是憑舊記憶選的**），改用 API 回覆建議的 `gemini-3.8-flash`；②成功回應後存下來的建議只有 57–63 字、從句子中間開始：新模型的「思考」用掉了我設的 1,200 輸出 token 上限；③單次要 27–79 秒（Vercel log），偶爾超過 100 秒的上限；④Google 偶爾回 503（需求量大）。
- 最後決定：提高輸出上限、排除 thought 片段、**回應沒有正常結束（非 STOP）就報錯而不是存殘文**；把殘缺的兩筆建議清掉；把頁面執行上限調到 120 秒；要求較低的思考程度（API 不接受就退回預設）；錯誤訊息顯示 Google 的原話與耗時。**後續（模型清單改查 API，不憑記憶）**：我請 subagent 讀 Gemini 官方文件確認參數，但沙箱不放行 `ai.google.dev`，讀不到，我沒有為此開放網域，也沒有拿記憶補上。改成在**已部署的 app**（它有使用者換過的新金鑰）加一支暫時的、需登入的診斷路由，直接問 API：
- `models.list` 回傳 49 個支援 generateContent 的模型，與我記憶中的版本差很多（2.5 系列已對新使用者停用）。
- 用同一個真實 prompt 實測輕量模型（thinkingLevel = minimal，thoughts = 0）：`gemini-3.1-flash-lite` **1.4–2.5 秒**（3 次）、`gemini-3.5-flash-lite` 2–15 秒、`gemini-flash-lite-latest` 10–17 秒。`thinkingBudget: 0` 被 API 以 400 拒絕。
- 決定：預設改為 `gemini-3.1-flash-lite` + `thinkingLevel: "minimal"`；診斷路由用完即移除（`8300862` 加入、下一個 commit 移除）。
- 新增 CLI `python -m src.pipeline.advice`（server 端呼叫、只存「正常結束且夠長」的回答）。**沙箱沒有金鑰、也無法注入 `x-goog-api-key`，所以這支 CLI 沒有對真實 Gemini 跑過**，只用 mock 的 HTTP 回應做測試；實際替 demo 的 5 個任務產生建議，是透過已部署 app 的同一套 server 端程式（報告頁按鈕背後的 action）完成的。
- 驗證：5 個任務的建議各 332–441 字，皆以「。」結尾、4–5 點、沒有寒暄或截斷。
- **還有一個問題**：內容裡出現「顯著優於」，但樣本只有 7 篇，而且「討論型平均觀看 698,000」其實是被一篇舊爆文拉高的。於是在 prompt 加一條規則（不得使用「顯著」等統計推論用語、平均值可能被極端值拉高時要提醒），重新產生。AI 的措辭過度宣稱，和 D-7 是同一類問題。

**D-10　交件前的修正：觀察用語、帳號觀察、AI 建議格式**
- 我的提問：①報告頁「觀察」在「僅真實資料」不可有 p 值與「顯著」，「全部資料」每點加「含 mock」前綴；②每個帳號補至少 3 點描述性觀察；③AI 建議要正確渲染、改用百分比與中位數；④重新產生按鈕要顯示「產生中…」。
- AI 回應：新增 `observations.ts`（只算中位數、篇數、方向）、`AdviceText`（安全的 Markdown 子集，不用 `dangerouslySetInnerHTML`）、`AdviceButton`；prompt 與資料改為百分比 + 中位數，並要求純文字。
- 發現的問題：①部署後驗證時發現，**沒有 mock 的 4 個任務**預設的「全部資料」仍顯示 p 值並被加上「含 mock」前綴（邏輯漏掉這種情形），改為「沒有 mock ＝ 全是真實資料」走描述性版本；②AI 建議重新產生時，我的腳本點了按鈕就跳頁，只有 3 / 5 個真的更新，是查資料庫才發現（又一次「不看畫面，查資料」）；③新內容仍把只有 1 篇的時段、分組當成建議依據，於是加規則「少於 3 篇不可當依據」；④Gemini 對輕量模型間歇回 503，加上重試；⑤`7b787e3` 推到 main 後 Vercel 沒有建立 production 部署（只有分支預覽），用 `create_deployment` 重新建置，並確認 production 指到最新 commit。
- 最後決定：以上都已修正並在部署網址重新驗證；TS 與 Python 版 prompt 的資料在 4 個帳號上逐欄比對一致。

**D-9　其他小修正**
- 第一版可行性腳本只把 `role="dialog"` 當登入牆，漏掉實際的 modal，被誤判成「捲 3 次都沒有新貼文」；改為同時比對 modal 文字（`docs/feasibility.md` 第 2 節）。
- 誤 commit 了 `__pycache__`：還沒 push，`git rm --cached` 後 amend，補上 `.gitignore`。
- 圖表：recharts 的進場動畫讓截圖一度是空白，圖例被依字母重新排序；關掉動畫、固定圖例順序。
- 分析的 permutation 檢定 p 值會因輸入順序有些微差異；排序後固定。
- `jieba` 在新版 setuptools 下建置失敗（`install_layout`）；用 `setuptools<70` 並寫進 README。

## 五、哪些部分 AI 幫助最大

**幫助最大**
- **骨架與重複性高的實作**：Next.js 頁面、Supabase `@supabase/ssr` 登入流程、RLS 與權限 SQL、CSV／JSON 匯出、表單與 server action。
- **除錯的速度**：沙箱網路與 proxy 的問題（Node 的 fetch 不走 proxy、金鑰型態、注入蓋掉使用者登入）、Vercel log 判讀、Gemini 的幾個失敗原因，都是靠 AI 邊試邊查在短時間內縮小範圍。
- **把驗收變成可重跑的測試**：兩個使用者的 RLS SQL、Playwright e2e、`validate_mock`、`insights_numbers`。
- **文件**：feasibility、mock 設計、分析輸出、README。

**幫助有限，需要人把關**
- **需求本身**：PRD 階段 AI 漏了題目要求的 6 個指標、規則有量級問題、官方 API 步驟憑記憶寫；這些都是靠我追問來源、要求區分「題目」與「AI 自訂」才發現。
- **合規與範圍**：是否登入、是否用 mock、哪些結論可以寫，都是我的決定（P4）。
- **措辭過度宣稱**：洞察初稿有 3 處說法比資料更強（D-7）；需要逐項對照原始資料才抓得到。
- **過時的知識**：模型名稱、Next 16 的 API 改名，都是「憑記憶」就會錯、查文件或實際呼叫才對。

**已知限制（與 AI 協作有關的部分）**
- 洞察只有 27 篇真實貼文，不可做統計推論，建議都是待驗證的假設（見 `reports/insights.md`）。
- AI 建議由 Gemini 依統計摘要產生，措辭曾有過度宣稱，已用 prompt 規則壓制但不保證；頁面標明「AI 產生、僅供參考」，且不使用 mock。CLI 沒有對真實 Gemini 跑過（沙箱沒有金鑰）。
- 沒有做完整的單元測試與 Docker（README「未做項目」）。
