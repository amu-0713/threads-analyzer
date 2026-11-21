import Link from "next/link";
import { notFound } from "next/navigation";
import { generateAdviceAction } from "@/app/dashboard/actions";
import { llmEnabled } from "@/lib/llm";
import ReportView from "@/components/report/ReportView";
import { UUID_RE } from "@/lib/format";
import { createClient } from "@/lib/supabase/server";
import type { Job, Post, Scope, Summary } from "@/lib/types";

// The AI-advice server action runs under this route and can take a while.
export const maxDuration = 60;

export default async function JobReportPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ scope?: string; advice_error?: string }>;
}) {
  const { id } = await params;
  const { scope: scopeParam, advice_error } = await searchParams;
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
        <h1 className="text-2xl font-bold">@{job.username} 分析報告</h1>
        {hasMock && (
          <nav className="flex gap-2" aria-label="資料範圍">{tab("all", "全部資料")}{tab("real", "僅真實資料")}</nav>
        )}
      </header>

      {job.status !== "done" || !summary ? (
        <div className="mt-6 rounded border border-current/30 p-4 text-sm">
          {job.status === "failed" ? (
            <>任務失敗：{job.error ?? "未知原因"}</>
          ) : (
            <>任務狀態：<b>{job.status}</b>。分析完成後（由本機 CLI 處理）這裡才會有報告。</>
          )}
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="opacity-60">匯出（{scope === "all" ? "全部資料" : "僅真實資料"}，含 source 欄位）：</span>
            <a className="rounded border border-current/30 px-3 py-1" href={`/dashboard/jobs/${id}/export?format=csv&scope=${scope}`}>CSV</a>
            <a className="rounded border border-current/30 px-3 py-1" href={`/dashboard/jobs/${id}/export?format=json&scope=${scope}`}>JSON</a>
          </div>
          <ReportView summary={summary} posts={posts ?? []} scope={scope} />
          <section className="mt-10">
            <h2 className="mb-3 text-lg font-semibold">AI 建議</h2>
            <div className="rounded border border-current/20 p-4 text-sm">
              <p className="mb-3 text-xs opacity-70">
                以下內容由 AI（Gemini）依<b>僅真實資料</b>的統計摘要產生，可能有誤，樣本很少時僅供參考；不含模擬（mock）資料。
              </p>
              {summary.llm_advice ? (
                <div className="whitespace-pre-wrap">{summary.llm_advice}</div>
              ) : (
                <p className="opacity-70">尚未產生。</p>
              )}
              <form action={generateAdviceAction} className="mt-3">
                <input type="hidden" name="id" value={id} />
                <button
                  disabled={!llmEnabled()}
                  className="rounded bg-foreground px-4 py-2 text-background disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {summary.llm_advice ? "重新產生 AI 建議" : "產生 AI 建議"}
                </button>
                {!llmEnabled() && <span className="ml-3 text-xs opacity-70">未設定 LLM_API_KEY，此功能停用</span>}
              </form>
              {advice_error && <p className="mt-2 text-red-600">產生失敗：{advice_error}</p>}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
