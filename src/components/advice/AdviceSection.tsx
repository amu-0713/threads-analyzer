"use client";

import { useState, useTransition } from "react";
import { generateAdviceAction } from "@/app/dashboard/actions";
import Link from "next/link";
import { useGoal } from "@/components/GoalContext";
import { taipeiStamp } from "@/lib/format";
import { DEFAULT_MODEL, FAST_MODEL, GOALS, GOAL_GROUP, MODELS, entryKey, isModel, modelLabel, type Entry, type Goal, type ModelId, type GuideStatus, type StableCounts, type Store } from "@/lib/advice";

function Card({ entry }: { entry: Entry }) {
  const a = entry.advice;
  return (
    <div className="space-y-3">
      <p className="rounded bg-current/5 p-3 font-medium">{a.summary}</p>
      {a.actions.map((x, i) => (
        <div key={i} className="rounded border border-current/20 p-3">
          <div className="text-xs opacity-60">做法 {i + 1}</div>
          <p className="mt-1 font-medium">{x.do}</p>
          <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="opacity-60">依據</dt>
            <dd>{x.why}</dd>
            <dt className="opacity-60">驗證</dt>
            <dd>{x.test}</dd>
          </dl>
        </div>
      ))}
      <p className="rounded border border-red-600/40 p-3 text-sm">
        <span className="font-semibold">避開：</span>
        {a.avoid}
      </p>
    </div>
  );
}

export default function AdviceSection({ jobId, store, counts, bases, status, enabled }: { jobId: string; store: Store; counts: StableCounts | null; bases: Record<Goal, string>; status: GuideStatus; enabled: boolean }) {
  const [entries, setEntries] = useState<Record<string, Entry>>(store.entries);
  // a cached entry counts only if it was written for the current writing guide and prompt version (same basis)
  const valid = (g: Goal, m: ModelId) => entries[entryKey(g, m)]?.basis === bases[g];
  // which model to show for a goal: the default model's advice if it exists, else the fast model's (so the page is never
  // empty when the default model ran out of quota), else the default model (generated on demand)
  const preferred = (g: Goal, current?: ModelId): ModelId =>
    current && valid(g, current) ? current : valid(g, DEFAULT_MODEL) ? DEFAULT_MODEL : valid(g, FAST_MODEL) ? FAST_MODEL : DEFAULT_MODEL;
  const { goal, setGoal } = useGoal();
  const [model, setModel] = useState<ModelId>(() => preferred(goal));
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const blockedFor = (g: Goal): string | null => {
    if (status === "missing") return "這個任務的分析還沒有寫作清單，請先在本機執行 python -m src.pipeline.run --analyze-only --job <任務 id> 重新分析，才能產生 AI 建議。";
    if (!counts) return "樣本太少，無法列出寫作清單，所以不產生 AI 建議。";
    if (counts[GOAL_GROUP[g]] === 0) return `「${g}」（${GOAL_GROUP[g]}）目前沒有前後期一致的寫法，暫不產生建議。`;
    return null;
  };
  const blocked = blockedFor(goal);
  // an entry written for an older writing guide (basis differs) is hidden until it is regenerated
  const stored = entries[entryKey(goal, model)];
  const entry = stored && stored.basis === bases[goal] ? stored : undefined;
  const stale = !!stored && !entry;

  const run = (g: Goal, m: ModelId) =>
    startTransition(async () => {
      setError(null);
      const r = await generateAdviceAction(jobId, g, m);
      if (r.ok) setEntries((prev) => ({ ...prev, [entryKey(g, m)]: r.entry }));
      else setError(r.error);
    });

  // Switching shows the cached advice for that goal + model. Picking a goal tab or pressing "use the fast model" generates right away
  // when there is none; changing the model in the dropdown NEVER sends a request: the person presses 產生.
  const pick = (g: Goal, m: ModelId, autoGenerate: boolean) => {
    setGoal(g);
    setModel(m);
    setError(null);
    const st = entries[entryKey(g, m)];
    if (autoGenerate && enabled && !blockedFor(g) && !(st && st.basis === bases[g])) run(g, m);
  };

  // too few real posts for a writing guide: no AI advice at all (not even the plain text an older version stored)
  if (status === "too_small") {
    return (
      <div className="rounded border border-current/20 p-4 text-sm">
        <p>樣本太少，不產生 AI 建議。</p>
        <p className="mt-1 text-xs opacity-70">真實貼文少於 20 篇時，無法列出前後期一致的寫法，所以不產生 AI 建議（登入模式約 40 篇可以）。</p>
      </div>
    );
  }

  return (
    <div className="rounded border border-current/20 p-4 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" aria-label="目標" className="flex gap-2">
          {GOALS.map((g) => (
            <button
              key={g}
              role="tab"
              aria-selected={g === goal}
              disabled={pending}
              onClick={() => pick(g, preferred(g, model), true)}
              className={`rounded border px-3 py-1 ${g === goal ? "bg-foreground text-background" : "border-current/30"} disabled:opacity-50`}
            >
              {g}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-2">
          <span className="opacity-70">模型</span>
          <select
            value={model}
            disabled={pending}
            onChange={(e) => isModel(e.target.value) && pick(goal, e.target.value, false)}
            className="rounded border border-current/30 bg-transparent p-1 disabled:opacity-50"
          >
            {MODELS.map((m) => (
              <option key={m.id} value={m.id}>{m.label}（{m.id}）</option>
            ))}
          </select>
        </label>
      </div>

      <p className="mt-3 text-xs opacity-70">
        以下內容由 AI（Gemini）依「僅真實資料」的分組寫作清單產生，只使用前後期一致的寫法，可能有誤，僅供參考；不含模擬（mock）資料。
      </p>
      <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs opacity-70">
        <li>兩個目標的做法可能相反，請依這篇貼文的目的擇一。</li>
        <li>
          <Link href="/dashboard/compare#insights" className="underline">比較頁洞察</Link>是跨帳號、看貼文目的的人工判讀；這裡只看單一帳號前後期一致的寫法，兩者可能不同。
        </li>
      </ul>

      {/* exactly one message at a time: generating > error > the advice > why there is none (blocked / outdated / disabled / not yet) */}
      <div className="mt-3" aria-live="polite">
        {pending ? (
          <p className="opacity-70">{model === DEFAULT_MODEL ? "產生中，約 10–20 秒" : "產生中，通常 5 秒內"}</p>
        ) : error ? (
          <div className="text-red-600">
            <p>{error.includes("今日額度已用完") ? error : `產生失敗：${error}`}</p>
            {error.includes("今日額度已用完") && model !== FAST_MODEL && (
              <button type="button" onClick={() => pick(goal, FAST_MODEL, true)} className="mt-2 rounded border border-current/40 px-3 py-1 text-foreground">
                改用快速模型（{FAST_MODEL}）產生
              </button>
            )}
          </div>
        ) : entry ? (
          <>
            {model === FAST_MODEL && !valid(goal, DEFAULT_MODEL) && (
              <p className="mb-2 text-xs opacity-70">預設模型（{DEFAULT_MODEL}）的建議尚未產生，先顯示快速模型的結果；可在上方切換模型。</p>
            )}
            <Card entry={entry} />
          </>
        ) : blocked ? (
          <p className="opacity-70">{blocked}</p>
        ) : stale ? (
          <p className="opacity-70">寫作清單或 prompt 已更新，之前產生的建議已失效，請按「產生」重新產生。</p>
        ) : !enabled ? (
          <p className="opacity-70">未設定 LLM_API_KEY，此功能停用。</p>
        ) : (
          <p className="opacity-70">尚未產生這個目標與模型的建議，請按「產生」。</p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button
          onClick={() => run(goal, model)}
          disabled={pending || !enabled || !!blocked}
          className="rounded bg-foreground px-4 py-2 text-background disabled:cursor-not-allowed disabled:opacity-40"
        >
          {pending ? "產生中…" : entry ? "重新產生" : "產生"}
        </button>
        {entry && !pending && (
          <span className="text-xs opacity-60">
            由 AI 產生，僅供參考・模型 {modelLabel(entry.model)}（{entry.model}）・{taipeiStamp(entry.generated_at)}
          </span>
        )}
      </div>

    </div>
  );
}
