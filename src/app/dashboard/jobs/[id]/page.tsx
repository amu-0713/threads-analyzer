import Link from "next/link";
import { notFound } from "next/navigation";
import { llmEnabled } from "@/lib/llm";
import PendingCommand from "@/components/PendingCommand";
import AdviceSection from "@/components/advice/AdviceSection";
import { GOALS, adviceBasis, guideStatus, parseStore, stableCounts } from "@/lib/advice";
import ReportView from "@/components/report/ReportView";
import { UUID_RE, modeLabel } from "@/lib/format";
import { createClient } from "@/lib/supabase/server";
import type { Job, Post, Scope, Summary } from "@/lib/types";

// The AI-advice server action runs under this route and can take a while.
export const maxDuration = 90;

export default async function JobReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ scope?: string }>;
}) {
  const { id } = await params;
  const { scope: scopeParam } = await searchParams;
  if (!UUID_RE.test(id)) notFound();

  const supabase = await createClient();
  // RLS: someone else's job id simply returns no row -> 404
  const { data: job } = await supabase.from("jobs").select("*").eq("id", id).maybeSingle<Job>();
  if (!job) notFound();

  const [{ data: summary }, { data: posts }] = await Promise.all([
    supabase.from("job_summaries").select("*").eq("job_id", id).maybeSingle<Summary>(),
    supabase.from("posts").select("*").eq("job_id", id).order("posted_at", { ascending: false }).returns<Post[]>(),
  ]);

  const hasMock = (summary?.metrics.all?.n_mock ?? 0) > 0;
  const scope: Scope = scopeParam === "real" ? "real" : "all";
  const tab = (s: Scope, label: string) => (
    <Link
      href={`/dashboard/jobs/${id}?scope=${s}`}
      className={`rounded border px-3 py-1 text-sm ${scope === s ? "bg-foreground text-background" : "border-current/30"}`}
    >
      {label}
    </Link>
  );

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <Link href="/dashboard" className="text-sm underline">← 任務列表</Link>
      <header className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">
          @{job.username} 分析報告
          <span className="ml-3 rounded border border-current/40 px-2 py-0.5 align-middle text-xs font-normal">{modeLabel(job.mode)}</span>
        </h1>
        {hasMock && (
          <nav className="flex gap-2" aria-label="資料範圍">{tab("all", "全部資料")}{tab("real", "僅真實資料")}</nav>
        )}
      </header>

      {job.status !== "done" || !summary ? (
        <div className="mt-6 rounded border border-current/30 p-4 text-sm">
          {job.status === "failed" ? (
            <>任務失敗：{job.error ?? "未知原因"}</>
          ) : (
            <>
              任務狀態：<b>{job.status}</b>。分析完成後（由本機 CLI 處理）這裡才會有報告。
              {job.status === "pending" && (
                <div className="mt-3">
                  <PendingCommand mode={job.mode} />
                </div>
              )}
            </>
          )}
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="opacity-60">匯出（{scope === "all" ? "全部資料" : "僅真實資料"}，含 source 欄位）：</span>
            <a className="rounded border border-current/30 px-3 py-1" href={`/dashboard/jobs/${id}/export?format=csv&scope=${scope}`}>CSV</a>
            <a className="rounded border border-current/30 px-3 py-1" href={`/dashboard/jobs/${id}/export?format=json&scope=${scope}`}>JSON</a>
          </div>
          <ReportView summary={summary} posts={posts ?? []} scope={scope} mode={job.mode} />
          <section className="mt-10">
            <h2 className="mb-3 text-lg font-semibold">AI 建議</h2>
            <AdviceSection jobId={id} store={parseStore(summary.llm_advice)} counts={stableCounts(summary)} bases={Object.fromEntries(GOALS.map((g) => [g, adviceBasis(g, summary)])) as Record<(typeof GOALS)[number], string>} status={guideStatus(summary)} enabled={llmEnabled()} />
          </section>
        </>
      )}
    </main>
  );
}
