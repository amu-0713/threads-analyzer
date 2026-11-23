// Gemini advice generator. Server-side only: the key comes from LLM_API_KEY and never reaches the browser.
// No path-alias imports (only relative ones) so the file can also be run directly with node for testing.
import { RESPONSE_SCHEMA, STRONG_MODEL, THINKING, parseAdvice, type AdviceContext, type AdviceObject, type Goal, type ModelId } from "./advice";

export function llmEnabled(): boolean {
  return Boolean(process.env.LLM_API_KEY);
}

type Variant = { thinking: boolean; schema: boolean };
// Tried in this order when the API answers 400 (a parameter this model does not accept): full request first, then
// without the thinking setting, then JSON mode without the schema.
const VARIANTS: Variant[] = [{ thinking: true, schema: true }, { thinking: false, schema: true }, { thinking: false, schema: false }];

async function callGemini(key: string, model: ModelId, prompt: string, v: Variant): Promise<Response> {
  const started = Date.now();
  return fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-goog-api-key": key },
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0.4,
        maxOutputTokens: 4096,
        responseMimeType: "application/json",
        ...(v.schema ? { responseSchema: RESPONSE_SCHEMA } : {}),
        ...(v.thinking ? { thinkingConfig: THINKING[model] } : {}),
      },
    }),
    signal: AbortSignal.timeout(40_000),
  }).catch((e: Error) => {
    throw new Error(`Gemini request failed after ${Math.round((Date.now() - started) / 1000)}s: ${e.message}`);
  });
}

/** One request with variant fallback (400) and a short back-off on 429/5xx. Returns the answer text (JSON). */
async function requestText(key: string, model: ModelId, prompt: string): Promise<string> {
  const started = Date.now();
  let vi = 0;
  let res = await callGemini(key, model, prompt, VARIANTS[vi]);
  while (res.status === 400 && vi < VARIANTS.length - 1) {
    console.log(`[llm] ${model} rejected variant ${vi} (400): ${(await res.text()).slice(0, 200)}`);
    res = await callGemini(key, model, prompt, VARIANTS[++vi]);
  }
  for (let attempt = 0; attempt < 2 && [429, 500, 502, 503, 504].includes(res.status); attempt++) {
    const body = (await res.clone().text()).replace(/\s+/g, " ");
    console.log(`[llm] ${model} ${res.status}, retry ${attempt + 1}: ${body.slice(0, 700)}`);
    // a per-day quota does not recover within seconds: say so instead of waiting and retrying
    if (res.status === 429 && /per day/i.test(body)) throw new Error(model === STRONG_MODEL ? "今日額度已用完，請改用快速模型" : "今日額度已用完，請明天再試");
    await new Promise((r) => setTimeout(r, 3000 * 2 ** attempt));
    res = await callGemini(key, model, prompt, VARIANTS[vi]);
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
  const text: string = (cand?.content?.parts ?? []).filter((p: { thought?: boolean }) => !p.thought).map((p: { text?: string }) => p.text ?? "").join("");
  console.log(`[llm] ${model} variant=${vi} answered in ${Date.now() - started}ms finishReason=${finish} chars=${text.length} usage=${JSON.stringify(json?.usageMetadata ?? {})}`);
  if (!text.trim()) throw new Error(`Gemini returned no text (finishReason=${finish ?? "none"})`);
  if (finish && finish !== "STOP") throw new Error(`Gemini answer was cut off (finishReason=${finish}); try again`);
  return text;
}

/** Structured advice for one goal. A reply that is not valid JSON / misses a field / uses inferential wording is retried once;
 *  if it still fails the reason is thrown and nothing is stored. */
export async function generateAdvice(model: ModelId, goal: Goal, prompt: string, ctx?: AdviceContext): Promise<AdviceObject> {
  const key = process.env.LLM_API_KEY;
  if (!key) throw new Error("LLM_API_KEY is not set");
  let lastError = "";
  for (let attempt = 0; attempt < 2; attempt++) {
    const text = await requestText(key, model, attempt === 0 ? prompt : `${prompt}\n\n（上一次的回應不合格：${lastError}。請修正後重新輸出。）`);
    try {
      return parseAdvice(text, goal, ctx);
    } catch (e) {
      lastError = e instanceof Error ? e.message : String(e);
      console.log(`[llm] invalid answer (attempt ${attempt + 1}): ${lastError}`);
    }
  }
  throw new Error(`AI 回應格式不合格（已重試一次）：${lastError}`);
}
