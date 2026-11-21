import Link from "next/link";
import CompareTable from "@/components/report/CompareTable";
import { UUID_RE, modeLabel } from "@/lib/format";
import { insightsHtml } from "@/lib/insights";
import { createClient } from "@/lib/supabase/server";
import type { Job, Summary } from "@/lib/types";

export default async function ComparePage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string | string[] }>;
}) {
  const { id } = await searchParams;
  const selected = [id ?? []].flat().filter((v) => UUID_RE.test(v));

  const supabase = await createClient();
  const { data: allJobs } = await supabase
    .from("jobs")
    .select("*")
    .eq("status", "done")
    .order("created_at", { ascending: false })
    .returns<Job[]>();
  const jobs = allJobs ?? [];
  const chosen = jobs.filter((j) => selected.includes(j.id));

  const { data: sums } = chosen.length
    ? await supabase.from("job_summaries").select("*").in("job_id", chosen.map((j) => j.id)).returns<Summary[]>()
    : { data: [] as Summary[] };
  const summaries = Object.fromEntries((sums ?? []).map((s) => [s.job_id, s]));

  const insights = insightsHtml();

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <Link href="/dashboard" className="text-sm underline">← 任務列表</Link>
      <h1 className="mt-3 text-2xl font-bold">多帳號比較</h1>
      <p className="mt-1 text-sm opacity-70">只使用真實貼文（不含 mock）。每個帳號只有 5–9 篇，差異僅供參考。</p>

      <form className="mt-6 rounded border border-current/20 p-4">
        <div className="mb-2 text-sm font-medium">選擇要比較的任務（至少 2 個）</div>
        {jobs.length === 0 ? (
          <p className="text-sm opacity-60">還沒有完成的任務。</p>
        ) : (
          <ul className="grid gap-1 sm:grid-cols-2">
            {jobs.map((j) => (
              <li key={j.id}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" name="id" value={j.id} defaultChecked={selected.includes(j.id)} />
                  @{j.username}
                  <span className="text-xs opacity-60">
                    {new Date(j.created_at).toLocaleDateString("zh-TW", { timeZone: "Asia/Taipei" })}・{modeLabel(j.mode)}・{j.post_count} 篇
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
        <button className="mt-3 rounded bg-foreground px-4 py-2 text-sm text-background">比較</button>
      </form>

      <section className="mt-8">
        {chosen.length < 2 ? (
          <p className="text-sm opacity-70">勾選至少 2 個任務後按「比較」。</p>
        ) : (
          <CompareTable jobs={chosen} summaries={summaries} />
        )}
      </section>

      {insights && (
        <section className="mt-12 border-t border-current/20 pt-8" id="insights">
          <h2 className="mb-1 text-xl font-bold">洞察與內容建議</h2>
          <p className="mb-4 text-sm opacity-70">
            依 4 個帳號共 27 篇真實貼文整理（不含 mock）。樣本很小，以下是待驗證的假設，不是統計結論。
            完整檔案：<code>reports/insights.md</code>
          </p>
          <article className="md-body" dangerouslySetInnerHTML={{ __html: insights }} />
        </section>
      )}
    </main>
  );
}
