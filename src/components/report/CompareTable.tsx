import { modeLabel, num, pct } from "@/lib/format";
import type { Job, Metrics, Summary } from "@/lib/types";

type Row = { label: string; hint?: string; cell: (m: Metrics, s: Summary) => string };

const ROWS: Row[] = [
  { label: "模式", hint: "未登入＝僅首屏；登入＝自己的工作階段，最多 40 篇", cell: () => "" },
  { label: "真實貼文數", cell: (m) => String(m.n_real) },
  { label: "平均觀看", hint: "≥1 萬為四捨五入值", cell: (m) => num(m.avg.views) },
  { label: "平均讚", cell: (m) => num(m.avg.likes, 1) },
  { label: "平均回覆", cell: (m) => num(m.avg.replies, 1) },
  { label: "平均轉發", cell: (m) => num(m.avg.reposts, 1) },
  { label: "平均引用", cell: (m) => num(m.avg.quotes, 1) },
  { label: "讚 中位數", cell: (m) => num(m.median.likes) },
  { label: "平均互動率", hint: "(讚+回覆+轉發+引用)÷觀看", cell: (m) => pct(m.avg_interaction_rate) },
  { label: "平均按讚率", cell: (m) => pct(m.avg_like_rate) },
  { label: "平均回覆率", cell: (m) => pct(m.avg_reply_rate) },
  { label: "平均字數", cell: (m) => num(m.avg.char_count, 0) },
  { label: "最多的貼文類型", cell: (m) => (m.post_types[0] ? `${m.post_types[0].type}（${m.post_types[0].n} 篇）` : "—") },
  { label: "常見關鍵字", cell: (m) => m.keywords.slice(0, 3).map((k) => k.word).join("、") || "—" },
  {
    label: "組別分布",
    hint: "低迷 / 討論 / 共鳴 / 未分組",
    cell: (_m, s) => {
      const c = s.group_analysis.real?.counts;
      return c ? `${c["低迷型"] ?? 0} / ${c["討論型"] ?? 0} / ${c["共鳴型"] ?? 0} / ${c["未分組"] ?? 0}` : "—";
    },
  },
];

export function jobLabel(j: Job) {
  return `@${j.username}`;
}

export default function CompareTable({ jobs, summaries }: { jobs: Job[]; summaries: Record<string, Summary | undefined> }) {
  return (
    <div className="overflow-x-auto">
      <table className="tbl w-full min-w-[480px] text-left text-sm">
        <thead>
          <tr className="border-b border-current/20">
            <th className="sticky left-0 bg-background"> </th>
            {jobs.map((j) => (
              <th key={j.id} className="text-right">
                {jobLabel(j)}
                <div className="text-xs font-normal opacity-60">{new Date(j.created_at).toLocaleDateString("zh-TW", { timeZone: "Asia/Taipei" })}・{modeLabel(j.mode)}</div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.label} className="border-b border-current/10 align-top">
              <td className="sticky left-0 bg-background">
                {r.label}
                {r.hint && <div className="text-xs opacity-50">{r.hint}</div>}
              </td>
              {jobs.map((j) => {
                const s = summaries[j.id];
                const m = s?.metrics.real;
                return (
                  <td key={j.id} className="text-right tabular-nums">
                    {r.label === "模式" ? modeLabel(j.mode) : m && s ? r.cell(m, s) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
