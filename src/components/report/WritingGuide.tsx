import RewriteExample from "@/components/report/RewriteExample";
import type { GroupName, StableFeature, WritingGuide as Guide } from "@/lib/types";

const ORDER: GroupName[] = ["共鳴型", "討論型", "低迷型"];
const GOAL: Record<GroupName, string> = { 共鳴型: "提高按讚、建立好感", 討論型: "帶動討論、收集意見", 低迷型: "要避開或改寫的寫法" };

const PHRASE: Record<string, [string, string]> = {
  char_median: ["字數較長", "字數較短"],
  question_share: ["較常出現提問句", "較少出現提問句"],
  link_share: ["較常含連結", "較少含連結"],
  evening_share: ["較常在晚間（18–23 點）發佈", "較少在晚間（18–23 點）發佈"],
};

function line(group: GroupName, f: StableFeature): string {
  const [hi, lo] = PHRASE[f.key] ?? [f.label + "較高", f.label + "較低"];
  const v = (x: number) => (f.is_share ? `${Math.round(x * 100)}%` : `${Math.round(x)} 字`);
  const what = f.is_share ? f.label : "中位數";
  return `${f.direction === "higher" ? hi : lo}：${group}的${what} ${v(f.group_value)}，其他貼文 ${v(f.others_value)}（${group} ${f.n_group} 篇、其他 ${f.n_others} 篇）`;
}

/** Writing guide per group: only features that point the same way in the older and the newer half of the real posts. */
export default function WritingGuide({ guide }: { guide: Guide | undefined }) {
  if (!guide) {
    return <p className="text-sm opacity-70">這個任務的分析還沒有寫作清單；請在本機執行 <code>python -m src.pipeline.run --analyze-only --job &lt;任務 id&gt;</code> 重新分析。</p>;
  }
  if (!guide.available || !guide.groups) {
    return <p className="text-sm opacity-70">樣本太少，無法列出寫作清單。</p>;
  }
  const example = guide.rewrite_example;
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {ORDER.map((g) => {
        const grp = guide.groups![g];
        return (
          <div key={g} className="rounded border border-current/20 p-3">
            <h3 className="font-semibold">{g}</h3>
            <p className="mt-0.5 text-xs opacity-70">目標：{GOAL[g]}</p>
            {grp.stable_features.length ? (
              <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm">
                {grp.stable_features.map((f) => <li key={f.key}>{line(g, f)}</li>)}
              </ul>
            ) : (
              <p className="mt-3 text-sm opacity-70">沒有前後期一致的寫法可以列出。</p>
            )}
            <p className="mt-3 text-xs opacity-60">只列出前後期一致的寫法（依 {guide.n_posts} 篇真實貼文）</p>
            {g === "低迷型" && example && <RewriteExample example={example} />}
          </div>
        );
      })}
    </div>
  );
}
