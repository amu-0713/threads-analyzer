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

export async function generateAdvice(prompt: string): Promise<string> {
  const key = process.env.LLM_API_KEY;
  if (!key) throw new Error("LLM_API_KEY is not set");
  const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${LLM_MODEL}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": key },
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: { temperature: 0.4, maxOutputTokens: 1200 },
    }),
    signal: AbortSignal.timeout(45_000),
  });
  if (!res.ok) {
    const raw = await res.text();
    let detail = raw.slice(0, 200);
    try {
      detail = JSON.parse(raw)?.error?.message ?? detail; // Google returns {"error": {"message": ...}}
    } catch {}
    throw new Error(`Gemini API ${res.status}: ${String(detail).slice(0, 200)}`);
  }
  const json = await res.json();
  const text: string | undefined = json?.candidates?.[0]?.content?.parts?.map((p: { text?: string }) => p.text ?? "").join("");
  if (!text?.trim()) throw new Error("Gemini returned no text (blocked or empty response)");
  return text.trim();
}
