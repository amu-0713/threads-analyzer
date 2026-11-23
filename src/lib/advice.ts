// Pure logic of the AI advice feature (goals, model whitelist, prompt input, validation, cache format).
// NO path-alias imports and no I/O, so it can be run directly with node for testing.
// src/pipeline/advice.py mirrors this file: keep the two in sync (checked by a parity script, see AI_LOG).

/* eslint-disable @typescript-eslint/no-explicit-any */

export const GOALS = ["擴大觸及", "帶動討論"] as const;
export type Goal = (typeof GOALS)[number];

/** goal -> the group whose stable features describe it; 低迷型 is always the "avoid" evidence */
export const GOAL_GROUP: Record<Goal, "共鳴型" | "討論型"> = { 擴大觸及: "共鳴型", 帶動討論: "討論型" };
export const GOAL_TEXT: Record<Goal, string> = {
  擴大觸及: "擴大觸及、建立好感（共鳴型：按讚百分位高）",
  帶動討論: "帶動討論、收集意見（討論型：回覆百分位高）",
};

/** Only these models can be chosen; the browser sends an id and the server checks it against this list. */
export const MODELS = [
  { id: "gemini-3.8-flash", label: "預設（Flash）" },
  { id: "gemini-3.1-flash-lite", label: "快速（Flash-Lite）" },
] as const;
export type ModelId = (typeof MODELS)[number]["id"];
export const DEFAULT_MODEL: ModelId = MODELS[0].id;
export const FAST_MODEL: ModelId = MODELS[1].id;
export const isModel = (m: unknown): m is ModelId => MODELS.some((x) => x.id === m);
export const isGoal = (g: unknown): g is Goal => (GOALS as readonly unknown[]).includes(g);
export const modelLabel = (id: string) => MODELS.find((m) => m.id === id)?.label ?? id;

/** thinking effort per model; both measured against the live API (see AI_LOG). Falls back to no config on a 400. */
export const THINKING: Record<ModelId, Record<string, string>> = {
  "gemini-3.8-flash": { thinkingLevel: "low" }, // "minimal" is rejected by this model (HTTP 400, see AI_LOG)
  "gemini-3.1-flash-lite": { thinkingLevel: "minimal" },
};

// ------------------------------------------------------------------------------------------------ prompt input
type Feature = {
  key: string; label: string; is_share: boolean; direction: "higher" | "lower"; group_value: number; others_value: number;
  n_group: number; n_others: number;
};

const fmtVal = (f: Feature, v: number) => (f.is_share ? `${Math.round(v * 100)}%` : `${Math.round(v)} 字`);

function featureForPrompt(group: string, f: Feature) {
  return {
    特徵: f.label,
    方向: f.direction === "higher" ? `${group}較高` : `${group}較低`,
    [group]: fmtVal(f, f.group_value),
    其他貼文: fmtVal(f, f.others_value),
    篇數: `${group} ${f.n_group} 篇、其他 ${f.n_others} 篇`,
  };
}

export type StableCounts = Record<"共鳴型" | "討論型" | "低迷型", number>;

/** Why there may be no guide: the analysis was never re-run with the new code ("missing") or the account has too few real posts. */
export type GuideStatus = "ok" | "missing" | "too_small";
export function guideStatus(summary: { group_analysis?: any }): GuideStatus {
  const wg = summary.group_analysis?.real?.writing_guide;
  return !wg ? "missing" : wg.available ? "ok" : "too_small";
}

/** Stable-feature counts per group, or null when the account has no writing guide (too few posts). */
export function stableCounts(summary: { group_analysis?: any }): StableCounts | null {
  const wg = summary.group_analysis?.real?.writing_guide;
  if (!wg?.available) return null;
  const c = (g: string) => (wg.groups?.[g]?.stable_features ?? []).length;
  return { 共鳴型: c("共鳴型"), 討論型: c("討論型"), 低迷型: c("低迷型") };
}

/** Bump when the prompt text changes (src/pipeline/advice.py has the same number; tests/test_advice.py fails if the prompt changes
 *  without this being bumped). It is part of the basis, so advice written with an older prompt is hidden and must be regenerated. */
export const PROMPT_VERSION = 3;

/** Fingerprint of the stable features behind one goal's advice (target group + 低迷型). An entry whose basis differs from the
 *  current one was written for an older guide or prompt: it is hidden and must be regenerated. Mirrored by advice_basis() in advice.py. */
export function adviceBasis(goal: Goal, summary: { group_analysis?: any }): string {
  const wg = summary.group_analysis?.real?.writing_guide;
  if (!wg?.available) return "";
  const part = (g: string) =>
    ((wg.groups?.[g]?.stable_features ?? []) as Feature[])
      .map((f) => `${g}:${f.key}:${f.direction}:${f.group_value}:${f.others_value}:${f.n_group}:${f.n_others}`)
      .join(",");
  return `p${PROMPT_VERSION}|${part(GOAL_GROUP[goal])}|${part("低迷型")}`;
}

/** Everything the model sees for one goal: stable features only (never the unstable ones), counts, representative traits. */
export function adviceInput(username: string, goal: Goal, summary: { group_analysis?: any }) {
  const ga = summary.group_analysis?.real;
  const wg = ga?.writing_guide;
  if (!wg?.available) throw new Error("樣本太少，無法列出寫作清單");
  const group = GOAL_GROUP[goal];
  const feats = (wg.groups?.[group]?.stable_features ?? []) as Feature[];
  if (!feats.length) throw new Error(`${goal}（${group}）目前沒有前後期一致的寫法，暫不產生建議`);
  const low = (wg.groups?.["低迷型"]?.stable_features ?? []) as Feature[];
  const rep = ga.groups?.[group]?.profile_of_representatives;
  const pct = (x: number | null | undefined) => (x == null ? null : `${(x * 100).toFixed(2)}%`);
  return {
    帳號: `@${username}`,
    目標: goal,
    目標說明: GOAL_TEXT[goal],
    真實貼文數: wg.n_posts,
    前後兩半各: wg.halves,
    分組篇數: { 共鳴型: ga.counts?.共鳴型, 討論型: ga.counts?.討論型, 低迷型: ga.counts?.低迷型 },
    目標組穩定特徵: feats.map((f) => featureForPrompt(group, f)),
    目標組代表貼文特徵: rep && {
      代表貼文數: rep.n,
      平均字數: rep.avg_char_count == null ? null : Math.round(rep.avg_char_count),
      平均按讚率: pct(rep.avg_like_rate),
      平均回覆率: pct(rep.avg_reply_rate),
      常見關鍵字: (rep.keywords ?? []).slice(0, 5).map((k: any) => k.word),
      提問句占比: rep.question_share == null ? null : `${Math.round(rep.question_share * 100)}%`,
      含連結占比: rep.link_share == null ? null : `${Math.round(rep.link_share * 100)}%`,
    },
    低迷型穩定特徵: low.map((f) => featureForPrompt("低迷型", f)),
  };
}

export function buildPrompt(username: string, goal: Goal, summary: { group_analysis?: any }): string {
  const data = adviceInput(username, goal, summary);
  return [
    "你是社群行銷顧問。以下是某個 Threads 帳號「僅真實貼文」的分析摘要（JSON）。",
    `任務：針對目標「${goal}」，告訴使用者「下一篇貼文」可以怎麼寫。`,
    "規則：",
    "1. 只能使用資料裡列出的穩定特徵。每點 actions 的 why 必須寫出：哪一組、哪個特徵、方向、篇數；特徵必須出現在「目標組穩定特徵」或「低迷型穩定特徵」，數字（百分比、字數、篇數）必須與資料一致。",
    "2. do 是使用者明天就能照著發文的具體寫法（例如：首篇控制在 120 字內，結尾用一個問句邀請回覆），不能只是統計事實；每一點 do 只依據一個特徵。",
    "3. test 說明怎麼驗證（例如：連續 4 篇 A/B 對照，比較回覆率中位數），要寫出比較的指標與篇數。",
    "4. avoid 用一句話說要避開什麼，依據低迷型穩定特徵；若「低迷型穩定特徵」是空的，寫「低迷型目前沒有前後期一致的特徵，沒有足夠依據指出要避開的寫法」。",
    "5. 用中立字詞描述；不可使用「顯著」「明顯優於」「統計上」「p 值」「證明」等推論用語；比率一律用百分比（例如 3.59%）；中位數優先；不可寫「顯示」「相關」「導致」「造成」等因果或關聯說法；do 與 avoid 裡的數字只能使用資料中出現的數字，不可自己新增門檻（例如資料是 82 字就不能寫 80 字）。",
    `6. 依實際篇數描述樣本：真實貼文 ${data.真實貼文數} 篇（依發文時間分成前後各約 ${data.前後兩半各.join("、")} 篇）。特徵方向只代表該組貼文與其他貼文的差別，不代表因果；summary 或 why 要提醒仍需實際測試。`,
    `7. 輸出 JSON：goal 必須是「${goal}」；summary 一句話（這個帳號要達成這個目標，下一篇該怎麼寫）；actions 2–4 點，每點有 do、why、test；avoid 一句話。`,
    "8. 精簡：summary、do、why、test、avoid 每欄一句話，各不超過 60 字；actions 以 2–3 點為主，只在穩定特徵夠多時才寫第 4 點。",
    "9. 資料沒有圖片或影片資訊，不可提及素材類型（例如圖片、影片、輪播、貼圖）；只能談文字寫法。",
    "10. summary、do、avoid 與 why 一樣，只能引用「目標組穩定特徵」或「低迷型穩定特徵」裡的特徵；不可提到清單以外的特徵（例如關鍵字、貼文類型、時段、字數等沒有列在穩定清單的項目）。「目標組代表貼文特徵」只是背景，不可當成依據或寫進建議。",
    "",
    JSON.stringify(data),
  ].join("\n");
}

// ------------------------------------------------------------------------------------------------ output schema + validation
export type Action = { do: string; why: string; test: string };
export type AdviceObject = { goal: Goal; summary: string; actions: Action[]; avoid: string };

/** Gemini responseSchema (OpenAPI subset) */
export const RESPONSE_SCHEMA = {
  type: "OBJECT",
  properties: {
    goal: { type: "STRING", enum: [...GOALS] },
    summary: { type: "STRING" },
    actions: {
      type: "ARRAY",
      minItems: 2,
      maxItems: 4,
      items: {
        type: "OBJECT",
        properties: { do: { type: "STRING" }, why: { type: "STRING" }, test: { type: "STRING" } },
        required: ["do", "why", "test"],
      },
    },
    avoid: { type: "STRING" },
  },
  required: ["goal", "summary", "actions", "avoid"],
};

const FORBIDDEN = /顯著|明顯優於|統計上|p\s*值|p\s*=|證明/;

/** Returns the advice object, or throws with the reason (invalid JSON, missing fields, inferential wording). */
export function parseAdvice(text: string, goal: Goal): AdviceObject {
  let obj: any;
  try {
    obj = JSON.parse(text);
  } catch {
    throw new Error("回應不是合法的 JSON");
  }
  const str = (v: unknown) => typeof v === "string" && v.trim().length > 0;
  if (obj?.goal !== goal) throw new Error(`goal 欄位不是「${goal}」`);
  if (!str(obj.summary)) throw new Error("缺少 summary");
  if (!Array.isArray(obj.actions) || obj.actions.length < 2 || obj.actions.length > 4) throw new Error("actions 必須是 2–4 點");
  for (const a of obj.actions) if (!str(a?.do) || !str(a?.why) || !str(a?.test)) throw new Error("某一點缺少 do／why／test");
  if (!str(obj.avoid)) throw new Error("缺少 avoid");
  const all = [obj.summary, obj.avoid, ...obj.actions.flatMap((a: Action) => [a.do, a.why, a.test])].join(" ");
  if (FORBIDDEN.test(all)) throw new Error("內容含有推論用語");
  return { goal, summary: obj.summary.trim(), actions: obj.actions.map((a: Action) => ({ do: a.do.trim(), why: a.why.trim(), test: a.test.trim() })), avoid: obj.avoid.trim() };
}

// ------------------------------------------------------------------------------------------------ cache in job_summaries.llm_advice
export type Entry = { goal: Goal; model: string; generated_at: string; n_posts: number; basis?: string; advice: AdviceObject };
export type Store = { version: 2; legacy_text: string | null; entries: Record<string, Entry> };
export const entryKey = (goal: string, model: string) => `${goal}|${model}`;

/** Old rows hold plain text; new rows hold this JSON. Both must keep working. */
export function parseStore(raw: string | null | undefined): Store {
  if (!raw) return { version: 2, legacy_text: null, entries: {} };
  try {
    const o = JSON.parse(raw);
    if (o && o.version === 2 && typeof o.entries === "object") return { version: 2, legacy_text: o.legacy_text ?? null, entries: o.entries };
  } catch {
    /* plain text from the first version */
  }
  return { version: 2, legacy_text: raw, entries: {} };
}

export function withEntry(raw: string | null | undefined, entry: Entry): string {
  const store = parseStore(raw);
  store.entries[entryKey(entry.goal, entry.model)] = entry;
  return JSON.stringify(store);
}
