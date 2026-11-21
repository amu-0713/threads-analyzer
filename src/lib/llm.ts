// Gemini advice generator. Server-side only: the key comes from LLM_API_KEY and never reaches the browser.
// No path-alias imports here so the file can also be run directly with node for testing.

export const LLM_MODEL = process.env.LLM_MODEL || "gemini-3.1-flash-lite";

export function llmEnabled(): boolean {
  return Boolean(process.env.LLM_API_KEY);
}

/* eslint-disable @typescript-eslint/no-explicit-any */
type PostLite = {
  source: string; views: number | null; likes: number; replies: number; reposts: number; quotes: number;
  char_count: number; post_type: string | null; posted_at: string | null;
};

const median = (xs: number[]): number | null => {
  if (!xs.length) return null;
  const a = [...xs].sort((x, y) => x - y), m = a.length >> 1;
  return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
};
const mean = (xs: number[]): number | null => (xs.length ? xs.reduce((x, y) => x + y, 0) / xs.length : null);
/** rates as percentages with 2 decimals ("3.59%"), so the model never sees 0.0359-style fractions */
const P = (x: number | null | undefined): string | null => (x == null || Number.isNaN(x) ? null : `${(x * 100).toFixed(2)}%`);
const N = (x: number | null | undefined, d = 0): number | null => (x == null ? null : Number(x.toFixed(d)));
const SLOTS: [string, number, number][] = [["凌晨 00–05", 0, 5], ["上午 06–11", 6, 11], ["下午 12–17", 12, 17], ["晚間 18–23", 18, 23]];
const BINS: [string, number, number][] = [["50 字以內", 0, 50], ["51–150 字", 51, 150], ["151–300 字", 151, 300], ["300 字以上", 301, 1e9]];
const hourTaipei = (iso: string) => Number(new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Taipei", hour: "2-digit", hour12: false })) % 24;

/** All numbers the model sees, computed from the account's REAL posts. Medians first; every rate is a percentage. */
export function adviceData(username: string, summary: { group_analysis: any; metrics?: any }, allPosts: PostLite[]) {
  const real = allPosts.filter((p) => p.source === "real" && p.views);
  const ir = (p: PostLite) => (p.likes + p.replies + p.reposts + p.quotes) / p.views!;
  const lr = (p: PostLite) => p.likes / p.views!;
  const rr = (p: PostLite) => p.replies / p.views!;
  const col = (f: (p: PostLite) => number, agg: (xs: number[]) => number | null) => agg(real.map(f));
  const g = summary.group_analysis?.real;
  const share = (x: number | null | undefined) => (x == null ? null : `${Math.round(x * 100)}%`);
  return {
    帳號: `@${username}`,
    真實貼文數: real.length,
    說明: "中位數是主要參考；平均數容易被單一爆文拉高。所有比率皆為百分比。",
    中位數: {
      觀看: N(col((p) => p.views!, median)), 讚: N(col((p) => p.likes, median), 1), 回覆: N(col((p) => p.replies, median), 1),
      轉發: N(col((p) => p.reposts, median), 1), 字數: N(col((p) => p.char_count, median)),
      互動率: P(col(ir, median)), 按讚率: P(col(lr, median)), 回覆率: P(col(rr, median)),
    },
    平均數: {
      觀看: N(col((p) => p.views!, mean)), 讚: N(col((p) => p.likes, mean), 1), 回覆: N(col((p) => p.replies, mean), 1),
      轉發: N(col((p) => p.reposts, mean), 1), 互動率: P(col(ir, mean)), 按讚率: P(col(lr, mean)), 回覆率: P(col(rr, mean)),
    },
    貼文類型: [...new Set(real.map((p) => p.post_type ?? "未分類"))].map((t) => {
      const ps = real.filter((p) => (p.post_type ?? "未分類") === t);
      return { 類型: t, 篇數: ps.length, 互動率中位數: P(median(ps.map(ir))) };
    }),
    字數區間: BINS.map(([label, lo, hi]) => {
      const ps = real.filter((p) => p.char_count >= lo && p.char_count <= hi);
      return { 區間: label, 篇數: ps.length, 互動率中位數: P(median(ps.map(ir))) };
    }).filter((b) => b.篇數 > 0),
    發文時段: SLOTS.map(([label, lo, hi]) => {
      const ps = real.filter((p) => p.posted_at && hourTaipei(p.posted_at) >= lo && hourTaipei(p.posted_at) <= hi);
      return { 時段: label, 篇數: ps.length, 互動率中位數: P(median(ps.map(ir))) };
    }).filter((b) => b.篇數 > 0),
    常見關鍵字: summary.metrics?.real?.keywords?.slice(0, 8).map((k: any) => k.word),
    分組篇數: g?.counts,
    各組代表貼文特徵: g && Object.fromEntries(Object.entries(g.groups ?? {}).map(([k, v]: [string, any]) => {
      const pr = v.profile_of_representatives;
      return [k, pr && { 代表貼文數: pr.n, 平均字數: N(pr.avg_char_count), 平均按讚率: P(pr.avg_like_rate), 平均回覆率: P(pr.avg_reply_rate),
        常見關鍵字: pr.keywords?.slice(0, 5).map((w: any) => w.word), 提問句占比: share(pr.question_share), 晚間占比: share(pr.evening_share), 含連結占比: share(pr.link_share) }];
    })),
  };
}

/** Compact, aggregate-only prompt from the *real-only* data (no raw post texts: they are untrusted input). */
export function buildPrompt(username: string, summary: { metrics?: any; group_analysis: any; insights?: any }, posts: PostLite[]): string {
  return [
    "你是社群媒體數據分析顧問。以下是某個 Threads 帳號「僅真實貼文」的統計摘要（JSON）。",
    "請用繁體中文，依據資料給 3–5 點具體、可執行的內容策略建議。",
    "規則：只能引用資料中有的數字與現象；樣本很少（真實貼文只有個位數）時，必須明講結論僅供參考、不可過度推論；",
    "不要編造資料中沒有的事實；不要提到你看不到的貼文內容；每點建議一句話說明依據。",
    "直接列出建議，不要自我介紹或寒暄。",
    "樣本只有個位數，不可使用「顯著」「明顯優於」等統計推論用語。",
    "引用數字時優先使用中位數；平均數容易被單一爆文拉高，若引用平均數要註明。",
    "所有比率一律用百分比表示（例如 3.59%），不要輸出 0.0359 這樣的小數。",
    "輸出純文字，不要使用任何 Markdown 符號（不要用 **、#、*、`）；每點以「1.」「2.」編號開頭，各佔一段。",
    "",
    JSON.stringify(adviceData(username, summary, posts)),
  ].join("\n");
}

async function callGemini(key: string, prompt: string, lowThinking: boolean): Promise<Response> {
  const started = Date.now();
  return fetch(`https://generativelanguage.googleapis.com/v1beta/models/${LLM_MODEL}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": key },
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0.4,
        maxOutputTokens: 4096,
        // Measured against the live API (2026-11-21): thinkingLevel "minimal" -> 0 thought tokens, ~2 s per call;
        // the default thinking took 30-80 s. (thinkingBudget: 0 is rejected by this model family.)
        ...(lowThinking ? { thinkingConfig: { thinkingLevel: "minimal" } } : {}),
      },
    }),
    signal: AbortSignal.timeout(60_000),
  }).catch((e: Error) => {
    throw new Error(`Gemini request failed after ${Math.round((Date.now() - started) / 1000)}s: ${e.message}`);
  });
}

export async function generateAdvice(prompt: string): Promise<string> {
  const key = process.env.LLM_API_KEY;
  if (!key) throw new Error("LLM_API_KEY is not set");
  const started = Date.now();
  let res = await callGemini(key, prompt, true);
  if (res.status === 400) {
    console.log(`[llm] low-thinking request rejected (400): ${(await res.text()).slice(0, 300)}; retrying with defaults`);
    res = await callGemini(key, prompt, false);
  }
  if (!res.ok) {
    const raw = await res.text();
    let detail = raw.slice(0, 200);
    try {
      detail = JSON.parse(raw)?.error?.message ?? detail; // Google returns {"error": {"message": ...}}
    } catch {}
    throw new Error(`Gemini API ${res.status}: ${String(detail).slice(0, 200)}`);
  }
  const json = await res.json();
  const cand = json?.candidates?.[0];
  const finish: string | undefined = cand?.finishReason;
  // keep only answer parts (thinking parts are flagged `thought`)
  const text: string | undefined = cand?.content?.parts
    ?.filter((p: { thought?: boolean }) => !p.thought)
    .map((p: { text?: string }) => p.text ?? "")
    .join("");
  console.log(`[llm] ${LLM_MODEL} answered in ${Date.now() - started}ms finishReason=${finish} chars=${text?.length ?? 0} usage=${JSON.stringify(json?.usageMetadata ?? {})}`);
  if (!text?.trim()) throw new Error(`Gemini returned no text (finishReason=${finish ?? "none"})`);
  // never store a cut-off answer
  if (finish && finish !== "STOP") throw new Error(`Gemini answer was cut off (finishReason=${finish}); try again`);
  return text.trim();
}
