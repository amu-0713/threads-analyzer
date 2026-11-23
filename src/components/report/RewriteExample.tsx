"use client";

import { useGoal } from "@/components/GoalContext";
import { GOAL_GROUP } from "@/lib/advice";
import { excerpt } from "@/lib/format";
import type { WritingGuide } from "@/lib/types";

/** The most typical 低迷型 post and how it differs from the stable writing of ONE group: the one behind the goal picked in the AI advice section. */
export default function RewriteExample({ example }: { example: NonNullable<WritingGuide["rewrite_example"]> }) {
  const { goal } = useGoal();
  const group = GOAL_GROUP[goal];
  const diffs = example.differences.filter((d) => d.group === group);
  return (
    <div className="mt-3 border-t border-current/10 pt-3 text-sm">
      <div className="text-xs font-semibold">改寫參考：最典型的一篇低迷型貼文</div>
      <p className="mt-1 opacity-80">「{excerpt(example.post.text, 40)}」</p>
      <p className="mt-1 text-xs opacity-70">依目前在「AI 建議」選的目標（{goal}），對照{group}的穩定寫法：</p>
      {diffs.length ? (
        <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">{diffs.map((d) => <li key={d.text}>{d.text}</li>)}</ul>
      ) : (
        <p className="mt-1 text-xs opacity-70">這篇與{group}的穩定寫法沒有不同之處。</p>
      )}
    </div>
  );
}
