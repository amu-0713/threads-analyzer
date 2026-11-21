// Gemini advice generator. Server-side only: the key comes from LLM_API_KEY and never reaches the browser.
// No path-alias imports here so the file can also be run directly with node for testing.

export const LLM_MODEL = process.env.LLM_MODEL || "gemini-3.8-flash";

export function llmEnabled(): boolean {
  return Boolean(process.env.LLM_API_KEY);
}

/* eslint-disable @typescript-eslint/no-explicit-any */
/** Compact, aggregate-only prompt from the *real-only* analysis (no raw post texts: they are untrusted input). */
export function buildPrompt(username: string, summary: { metrics: any; group_analysis: any; insights: any }): string {
  const m = summary.metrics?.real;
  const g = summary.group_analysis?.real;
  const data = {
    account: `@${username}`,
    real_posts: m?.n_real,
    averages: m?.avg,
    avg_interaction_rate: m?.avg_interaction_rate,
    avg_like_rate: m?.avg_like_rate,
    avg_reply_rate: m?.avg_reply_rate,
    post_types: m?.post_types,
    length_vs_interaction: m?.length_vs_interaction,
    top_keywords: m?.keywords?.slice(0, 8),
    group_counts: g?.counts,
    group_profiles: g && Object.fromEntries(Object.entries(g.groups ?? {}).map(([k, v]: [string, any]) => [k, { n_members: v.n_members, profile: v.profile_of_representatives }])),
    hypothesis_checks: summary.insights?.real?.map((i: any) => i.text),
  };
  return [
    "你是社群媒體數據分析顧問。以下是某個 Threads 帳號「僅真實貼文」的統計摘要（JSON）。",
    "請用繁體中文，依據資料給 3–5 點具體、可執行的內容策略建議。",
    "規則：只能引用資料中有的數字與現象；樣本很少（真實貼文只有個位數）時，必須明講結論僅供參考、不可過度推論；",
    "不要編造資料中沒有的事實；不要提到你看不到的貼文內容；每點建議一句話說明依據。",
    "",
    JSON.stringify(data),
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
        maxOutputTokens: 8192,
        // The default "thinking" made one call take 30-80 s; ask for less (retried without if the API rejects it).
        ...(lowThinking ? { thinkingConfig: { thinkingLevel: "low" } } : {}),
      },
    }),
    signal: AbortSignal.timeout(100_000),
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
