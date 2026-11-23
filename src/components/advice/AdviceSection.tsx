"use client";

import { useState, useTransition } from "react";
import { generateAdviceAction } from "@/app/dashboard/actions";
import AdviceText from "@/components/AdviceText";
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
  const [goal, setGoal] = useState<Goal>(GOALS[0]);
  const [model, setModel] = useState<ModelId>(DEFAULT_MODEL);
  const [entries, setEntries] = useState<Record<string, Entry>>(store.entries);
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

  // switching shows the cached advice for that goal + model; if there is none, it is generated right away
  const pick = (g: Goal, m: ModelId) => {
    setGoal(g);
    setModel(m);
    setError(null);
    const st = entries[entryKey(g, m)];
    if (enabled && !blockedFor(g) && !(st && st.basis === bases[g])) run(g, m);
  };

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
              onClick={() => pick(g, model)}
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
            onChange={(e) => isModel(e.target.value) && pick(goal, e.target.value)}
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

      <div className="mt-3" aria-live="polite">
        {pending ? (
          <p className="opacity-70">{model === DEFAULT_MODEL ? "產生中，約 10–20 秒" : "產生中，通常 5 秒內"}</p>
        ) : entry ? (
          <Card entry={entry} />
        ) : blocked ? (
          <p className="opacity-70">{blocked}</p>
        ) : stale ? (
          <p className="opacity-70">寫作清單已更新，之前產生的建議已失效，請按「產生」重新產生。</p>
        ) : !enabled ? (
          <p className="opacity-70">未設定 LLM_API_KEY，此功能停用。</p>
        ) : (
          <p className="opacity-70">尚未產生這個目標與模型的建議。</p>
        )}
        {error && (
          <div className="mt-2 text-red-600">
            <p>{error.includes("今日額度已用完") ? error : `產生失敗：${error}`}</p>
            {error.includes("今日額度已用完") && model !== FAST_MODEL && (
              <button type="button" onClick={() => pick(goal, FAST_MODEL)} className="mt-2 rounded border border-current/40 px-3 py-1 text-foreground">
                改用快速模型（{FAST_MODEL}）產生
              </button>
            )}
          </div>
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

      {store.legacy_text && (
        <details className="mt-4 text-xs">
          <summary className="cursor-pointer opacity-70">舊版建議（純文字，改版前產生）</summary>
          <div className="mt-2 opacity-80">
            <AdviceText text={store.legacy_text} />
          </div>
        </details>
      )}
    </div>
  );
}
