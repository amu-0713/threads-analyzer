import { NextResponse, type NextRequest } from "next/server";
import { toCsv, toRecord } from "@/lib/export";
import { UUID_RE } from "@/lib/format";
import { createClient } from "@/lib/supabase/server";
import type { Job, Post, Summary } from "@/lib/types";

/** GET /dashboard/jobs/<id>/export?format=csv|json&scope=all|real  (RLS: only the owner's rows come back) */
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const sp = request.nextUrl.searchParams;
  const format = sp.get("format") === "json" ? "json" : "csv";
  const scope = sp.get("scope") === "real" ? "real" : "all";
  if (!UUID_RE.test(id)) return new NextResponse("Not found", { status: 404 });

  const supabase = await createClient();
  const { data: job } = await supabase.from("jobs").select("*").eq("id", id).maybeSingle<Job>();
  if (!job) return new NextResponse("Not found", { status: 404 });

  let q = supabase.from("posts").select("*").eq("job_id", id).order("posted_at", { ascending: false });
  if (scope === "real") q = q.eq("source", "real");
  const { data: posts, error } = await q.returns<Post[]>();
  if (error) return new NextResponse(error.message, { status: 500 });

  const filename = `threads_${job.username}_${scope}.${format}`;
  const headers = { "Content-Disposition": `attachment; filename="${filename}"`, "Cache-Control": "no-store" };

  if (format === "csv") {
    return new NextResponse(toCsv(posts ?? []), { headers: { ...headers, "Content-Type": "text/csv; charset=utf-8" } });
  }
  const { data: summary } = await supabase.from("job_summaries").select("*").eq("job_id", id).maybeSingle<Summary>();
  const body = {
    job: { id: job.id, username: job.username, mode: job.mode, status: job.status },
    scope,
    exported_at: new Date().toISOString(),
    counts: { posts: posts?.length ?? 0, real: posts?.filter((p) => p.source === "real").length ?? 0, mock: posts?.filter((p) => p.source === "mock").length ?? 0 },
    note: "source = 'mock' rows are synthetic and do not represent the account's real performance.",
    posts: (posts ?? []).map(toRecord),
    summary: summary && {
      metrics: summary.metrics[scope], top_posts: summary.top_posts[scope],
      group_analysis: summary.group_analysis[scope], insights: summary.insights[scope],
    },
  };
  return new NextResponse(JSON.stringify(body, null, 2), { headers: { ...headers, "Content-Type": "application/json; charset=utf-8" } });
}
