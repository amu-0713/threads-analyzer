# T1 可行性測試：未登入用 Playwright 爬取 Threads

- 測試日期：2026-11-20（UTC）
- 腳本：`scripts/feasibility_test.py`（Python 3.13、Playwright 1.65.2、Chromium）
- 原始輸出：`data/feasibility/7eleventw_raw.json`（主測）、`data/feasibility/dcard.tw_raw.json`（交叉驗證），各附一張結束時的截圖 `*_final.png`
- 條件：不登入、不使用任何帳密或 cookie；每次捲動間隔 1–2 秒

## TL;DR

**未登入只拿得到個人頁首屏約 7–9 篇（含置頂），第一次捲動就會跳出登入牆，抓不到 30 篇。**
首屏貼文的欄位很完整（JSON 取得率 100%），**唯獨觀看數完全拿不到**。
正式方案不能只靠「未登入 Playwright」，需要 fallback，建議見最後一節。

## 1. 測試帳號挑選

條件：台灣公開品牌帳號、發文 50 篇以上、近期活躍。先用一次未登入的頁面載入探查 7 個候選帳號：

| 帳號 | 狀態 | 粉絲 | 首屏最新貼文 | 判斷 |
|---|---|---|---|---|
| **@7eleventw**（7-ELEVEn Taiwan） | 公開、已驗證 | 40 萬 | 2026-11-20（當天，近兩天 5 篇） | ✅ **選為主測** |
| @dcard.tw（Dcard） | 公開 | 萬級 | 2026-11-20（當天多篇） | ✅ 用來交叉驗證 |
| @starbuckstw（星巴克） | 公開 | 萬級 | 2026-10-07 | ⚠️ 符合條件，但近一個多月沒發文，活躍度較低 |
| @pchome24h（PChome 24h） | 公開 | 萬級 | 2026-11-15 | 符合，作為備選 |
| @familymart.tw、@pxmart.tw、@gogoro_tw | 頁面標題是「Threads • 登入」，沒有貼文 | — | — | ❌ 帳號名稱可能不存在或打錯，排除 |

**選 @7eleventw 的理由**：公開且已驗證的大型品牌、粉絲多、互動數分布廣（單篇讚數從 7 到 502 都有，適合做互動分析）、測試當天仍在發文、發文頻率高（近兩天 5 篇，加上 10 月的活動貼文）。

**限制說明**：Threads 個人頁**不顯示貼文總數**，而未登入又只看得到首屏，所以「50 篇以上」**無法在未登入狀態下直接驗證**。這裡是根據發文頻率（每天多篇）和帳號規模推估，並非實際數過。

## 2. 未登入能載入幾篇？何時遇到登入牆？

| 帳號 | 模式 | 載入篇數 | 登入牆 | 停止原因 |
|---|---|---|---|---|
| @7eleventw | 有畫面（xvfb 虛擬螢幕） | **7**（含 2 篇置頂的 10 月貼文） | **第 1 次捲動後**，在第 8 篇之前 | `login_wall` |
| @dcard.tw | `--headless` | **9**（含 1 篇置頂的 6 月貼文） | **第 1 次捲動後**，在第 10 篇之前 | `login_wall` |

- 頁面載入時沒有登入牆；**第一次捲動**後會出現一個無法關閉的置中 modal「透過 Threads 暢所欲言 → 使用 Instagram 帳號繼續」，背景頁面也不再載入新貼文。
- 整個過程中**沒有任何分頁用的 GraphQL 請求**（只有一個 216 bytes 的 `fetchBarcelonaExperimentQuery`）。所有貼文都來自伺服器端渲染（SSR）時內嵌的 JSON，未登入時根本不會觸發「載入更多」。
- 有畫面和 headless 兩種模式結果一致。
- 第一版腳本只把 `role="dialog"` 視為登入牆，結果漏抓這個 modal，被誤判成「捲 3 次都沒有新貼文」。已改成同時比對 modal 文字。右側欄常駐的「登入或註冊 Threads」小框不算登入牆。
- 依照「不繞過限制」的原則，**沒有**用 JS 移除 modal 或偽造 cookie 去嘗試載入更多。

## 3. 欄位取得狀況（@7eleventw，n = 7）

| 欄位 | DOM 取得率 | JSON 取得率 | 建議來源 | 說明 |
|---|---|---|---|---|
| 發文時間 | 100% | 100% | JSON `taken_at`（Unix 秒） | DOM 的 `<time datetime>` 也有，精度相同 |
| 文字內容 | 100% | 100% | JSON `caption.text` | dcard.tw 有 1 篇 `caption` 為 null（JSON 88.9%），DOM 有抓到文字，正式版需要用 DOM 補值，或改讀其他文字欄位 |
| **觀看／曝光數** | **0%** | **0%** | — | 見第 4 節 |
| 讚 | 100% | 100% | JSON `like_count` | |
| 回覆 | 57.1% | 100% | JSON `text_post_app_info.direct_reply_count` | 數字為 0 時 DOM 按鈕不顯示數字，腳本照規則記為 null |
| 轉發 | 57.1% | 100% | JSON `text_post_app_info.repost_count` | **DOM 的「轉發」數字 = 轉發 + 引用**（已驗證：442 篇那則 32+2=34、502 篇那則 21+8=29），無法拆開 |
| 引用 | 0% | 100% | JSON `text_post_app_info.quote_count` | 只有 JSON 能單獨取得 |
| 貼文 URL | 100% | 100% | JSON `code` 組成 `https://www.threads.com/@<user>/post/<code>` | |
| （附加）分享數 | DOM 有顯示 | JSON `text_post_app_info.reshare_count` | JSON | 題目沒要求，但可以當作額外的互動指標 |

**結論：JSON（SSR 內嵌）的欄位明顯比 DOM 完整且結構化**，引用數更是只有 JSON 有。DOM 只適合作為備援或交叉驗證。dcard.tw 的結果相同（JSON 的讚、回覆、轉發、引用都是 100%）。

## 4. 觀看／曝光數拿得到嗎？

**拿不到。**

- 掃描每篇貼文 JSON 中所有含 `view`、`impression`、`play_count`、`reach` 的 key，只找到 `like_and_view_counts_disabled`（值為 `false`，只是開關）和 `text_post_app_info.public_view_count_card_attachment_info`（值為 `null`），**沒有任何觀看數的數值欄位**。
- DOM 上也沒有觀看數。Threads 公開頁面本來就不對外顯示文字貼文的觀看數。
- 依照「不猜」的原則，所有貼文的 `views` 都記為 `null`。PRD 的互動率分母不能用觀看數，建議改用**粉絲數**（個人頁可取得，例如「40 萬位粉絲」）或「讚 + 回覆 + 轉發 + 引用」的絕對值。
- 只有帳號擁有者透過官方 Threads API 的 Insights（`views` metric，需要 `threads_manage_insights` 權限）才能拿到觀看數，也就是只能查**自己的帳號**。

## 5. 遇到的錯誤與限制

1. **登入牆**：第一次捲動就擋住，最多只拿得到 7–9 篇，這是最主要的限制。
2. **雲端沙箱網路**：一開始 threads.com 被環境的網路政策擋住（`ERR_TUNNEL_CONNECTION_FAILED`），使用者開放網域後才恢復。`playwright install chromium` 也因為 CDN 被擋而失敗，腳本會自動改用預裝的 Chromium（`/opt/pw-browsers/chromium`，也可以用 `PW_CHROMIUM_PATH` 或 `--executable-path` 指定）。在一般電腦上照常 `playwright install chromium` 即可。
3. **雲端沒有螢幕**：有畫面模式是在 `xvfb-run` 虛擬螢幕上跑的，結果和 headless 一致。
4. **DOM 結構不穩定**：互動按鈕的 svg 標籤放在 `title` 屬性，不是 `aria-label`，且文字跟著介面語系（zh-TW：讚／留言／轉發／分享）；數字為 0 時不顯示；class 名稱是混淆過的。DOM 解析很脆弱。
5. **置頂貼文**：首屏包含舊的置頂貼文（7eleventw 是 10 月、dcard.tw 是 6 月），排「最近 N 篇」時要依 `taken_at` 排序，或排除置頂貼文。
6. **轉發與引用合併**：DOM 只顯示合併後的數字。

## 6. 建議的正式爬取方式

| 方案 | 能否滿 30 篇 | 觀看數 | 合規與穩定性 | 評估 |
|---|---|---|---|---|
| A. 未登入 Playwright（本次測試） | ❌ 只有 7–9 篇 | ❌ | 合規，但改版就容易壞 | 只能當「即時取樣」 |
| B. 登入後用 Playwright 捲動 | 可能可以 | ❌ | 違反題目限制（不可登入），也有違反服務條款和封號的風險 | **不採用** |
| C. 官方 Threads API | 只能查**已授權的自己帳號**（`/me/threads` + Insights 有觀看數）。查任意公開帳號要靠 profile discovery 類權限，需要 App Review，**是否開放、會回傳哪些欄位還要再查證** | ✅（僅限自己的帳號） | 最合規、最穩定 | 適合「分析自己的帳號」這種情境 |
| D. Mock dataset | ✅ | 可以模擬 | 無風險 | 用來展示分析流程 |

**建議（混合式）**：
1. 主流程保留 **Playwright 未登入 + 解析 SSR 內嵌 JSON**（優先讀 JSON，DOM 只當備援），誠實呈現「實際抓到 N 篇」。這符合題目「指定用 Playwright」的要求。
2. 不足 30 篇時，**自動切換到 mock dataset**。mock 的 schema 直接沿用本次實測的欄位（`taken_at`、`caption.text`、`like_count`、`direct_reply_count`、`repost_count`、`quote_count`、`reshare_count`、`code`），數值分布參考實測貼文。在 UI 和報告中明確標示「實測 N 篇 + 模擬 M 篇」以及原因：未登入有登入牆。
3. 架構預留官方 API 的資料來源介面。如果使用者授權自己的帳號，就改走 API，並開放觀看數欄位。
4. PRD 的欄位定稿：`views` 設為**選填（nullable）**；互動率改用 `(讚+回覆+轉發+引用) / 粉絲數`；轉發和引用分開存。

## 7. 官方 API（文件查證，未實測）

- 查證日期：2026-11-20。直接讀 Meta 官方文件，**沒有申請 token，也沒有對 API 實際發請求**。`scripts/api_test.py` 已寫好但未執行。
- 文件出處（`https://developers.facebook.com/documentation/threads/` 底下）：
  - [retrieve-and-discover-posts/retrieve-posts](https://developers.facebook.com/documentation/threads/retrieve-and-discover-posts/retrieve-posts)：`/profile_posts` 的權限、限制與欄位
  - [insights](https://developers.facebook.com/documentation/threads/insights)：單篇貼文的互動指標
  - [get-started](https://developers.facebook.com/documentation/threads/get-started)：權限、tester 與 token
  - [overview](https://developers.facebook.com/documentation/threads/overview)：速率限制
  - [threads-use-case](https://developers.facebook.com/documentation/development/create-an-app/threads-use-case)：app 設定
- 圖例：✅ 文件明確寫出；❓ 文件沒寫，未確認。

| 問題 | 結論 | 文件依據 |
|---|---|---|
| 端點與權限 | ✅ `GET /profile_posts?username=<帳號>`，需要 `threads_basic` 和 `threads_profile_discovery`。`username` 必須完全相符。 | retrieve-posts |
| 能回傳哪些欄位 | ✅ 與 app-scoped user 貼文相同（少了 `owner`）：`id, media_product_type, media_type, media_url, permalink, username, text, timestamp, shortcode, is_quote_post, quoted_post, reposted_post, topic_tag, link_attachment_url, is_verified` 等。 | retrieve-posts 的欄位表 |
| 讚／回覆／轉發／引用／觀看數 | ✅ **欄位表中沒有任何一項**，`profile_posts` 拿不到互動數。 | retrieve-posts 的欄位表 |
| 互動數的其他來源 | ✅ 只有 `GET /{media-id}/insights`，指標 `views`、`likes`、`replies`、`reposts`、`quotes`。文件描述為讀取「users' own」貼文，也就是只能查自己的。`views` 標示為 in development。 | insights |
| 沒過 App Review 能否查別人的公開帳號 | ✅ **基本不能。** 原文：standard access 下只能取得部分 Meta 官方帳號（@meta、@threads、@instagram、@facebook）的貼文。其他公開帳號需要進階存取（Advanced Access），也就是要過 App Review。7eleventw 不在清單內，預期被拒；錯誤訊息實際長相未確認。 | retrieve-posts |
| 帳號資格 | ✅ 只回傳追蹤者 100 人以上的公開帳號。 | retrieve-posts |
| 分頁 | ✅ 回傳 `paging.cursors.before/after`，另有 `since`、`until`、`limit` 參數。❓ `limit` 的上限文件沒寫。 | retrieve-posts 範例 |
| 速率限制 | ✅ `profile_posts`：每位使用者滾動 24 小時內最多 1,000 次請求。一般 API 另有 `4800 × impressions` 的 24 小時呼叫上限。 | retrieve-posts、overview |
| Token | ✅ 開發測試時可在 Graph API Explorer 產生；要查自己帳號需先把帳號加為 Threads Tester 並在 threads.com 設定接受邀請。短期 token 1 小時，長期 token 60 天。❓ Explorer 的實際操作畫面文件沒寫。 | get-started |
| API 主機 | 文件範例用 `graph.threads.com`；較舊的 `graph.threads.net` 沙箱可連線，是否仍等效❓未確認。 | 文件範例；沙箱連線測試 |

### 結論

1. **官方 API 無法完成本題目標。** 要分析第三方品牌帳號，需要進階存取（App Review），開發模式只能查 Meta 的 4 個官方帳號；而且即使查得到，`profile_posts` 也沒有任何互動數欄位，只能拿到文字、時間、連結。
2. 觀看數和互動數只能由**帳號擁有者**授權自己的帳號，透過 `/{media-id}/insights` 取得。因此官方 API 只適合「分析自己的帳號」的情境，這一條要留給 PRD 作為擴充方向。
3. 對這份筆試，官方 API 不是可行的主要資料來源。依第 6 節的混合式建議，主流程仍是未登入 Playwright，不足時用 mock dataset。
4. 未實測的部分（實際錯誤訊息、查 @meta 時的真實回傳）不影響以上結論，這些結論都來自文件本身。
