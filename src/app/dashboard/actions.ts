"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { UUID_RE } from "@/lib/format";
import { buildPrompt, generateAdvice, llmEnabled } from "@/lib/llm";
import { normalizeUsername } from "@/lib/username";

export async function createJob(formData: FormData) {
  const username = normalizeUsername(String(formData.get("target") ?? ""));
  if (!username) {
    redirect(
      "/dashboard?" +
        new URLSearchParams({ error: "請輸入有效的 Threads 帳號或個人頁網址" }),
    );
  }

  const supabase = await createClient();
  // user_id defaults to auth.uid() in the DB; RLS rejects anything else.
  const { error } = await supabase.from("jobs").insert({ username });
  if (error) {
    redirect("/dashboard?" + new URLSearchParams({ error: error.message }));
  }
  revalidatePath("/dashboard");
  redirect("/dashboard");
}

function back(params: Record<string, string>): never {
  redirect("/dashboard?" + new URLSearchParams(params));
}

/** Re-run: set the job back to 'pending'; the local CLI (python -m src.pipeline.run --pending) does the work. */
export async function rerunJob(formData: FormData) {
  const id = String(formData.get("id") ?? "");
  if (!UUID_RE.test(id)) back({ error: "無效的任務 ID" });
  const supabase = await createClient();
  // RLS + column grants: only the owner, only done/failed jobs, only -> pending.
  const { data, error } = await supabase
    .from("jobs")
    .update({ status: "pending", error: null, finished_at: null })
    .eq("id", id)
    .select("id");
  if (error) back({ error: error.message });
  if (!data?.length) back({ error: "只能重跑已完成或失敗的任務" });
  revalidatePath("/dashboard");
  back({ notice: "已重設為 pending，請在本機執行 python -m src.pipeline.run --pending" });
}

/** Delete a job; posts and job_summaries go with it (ON DELETE CASCADE). The confirm dialog is on the button. */
export async function deleteJob(formData: FormData) {
  const id = String(formData.get("id") ?? "");
  if (!UUID_RE.test(id)) back({ error: "無效的任務 ID" });
  const supabase = await createClient();
  const { data, error } = await supabase.from("jobs").delete().eq("id", id).select("id");
  if (error) back({ error: error.message });
  if (!data?.length) back({ error: "找不到這個任務" });
  revalidatePath("/dashboard");
  back({ notice: "已刪除任務" });
}

/** T12: generate AI advice from the real-only analysis and store it in job_summaries.llm_advice. */
export async function generateAdviceAction(formData: FormData) {
  const id = String(formData.get("id") ?? "");
  const to = (params: Record<string, string>) => redirect(`/dashboard/jobs/${id}?` + new URLSearchParams(params));
  if (!UUID_RE.test(id)) back({ error: "無效的任務 ID" });
  if (!llmEnabled()) to({ advice_error: "尚未設定 LLM_API_KEY" });

  const supabase = await createClient();
  const { data: job } = await supabase.from("jobs").select("username").eq("id", id).maybeSingle();
  const { data: summary } = await supabase.from("job_summaries").select("metrics, group_analysis, insights").eq("job_id", id).maybeSingle();
  if (!job || !summary) to({ advice_error: "找不到分析結果" });
  const { data: posts } = await supabase
    .from("posts")
    .select("source, views, likes, replies, reposts, quotes, char_count, post_type, posted_at")
    .eq("job_id", id)
    .eq("source", "real");

  let advice: string;
  try {
    advice = await generateAdvice(buildPrompt(job!.username, summary!, posts ?? []));
  } catch (e) {
    to({ advice_error: e instanceof Error ? e.message : "產生失敗" });
  }
  const { data, error } = await supabase.from("job_summaries").update({ llm_advice: advice! }).eq("job_id", id).select("job_id");
  if (error || !data?.length) to({ advice_error: error?.message ?? "無法儲存建議" });
  revalidatePath(`/dashboard/jobs/${id}`);
  to({});
}
