"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { UUID_RE } from "@/lib/format";
import { actionCount, adviceBasis, buildPrompt, isGoal, isModel, withEntry, type Entry } from "@/lib/advice";
import { generateAdvice, llmEnabled } from "@/lib/llm";
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
  const mode = formData.get("mode") === "login" ? "login" : "anonymous";
  const { error } = await supabase.from("jobs").insert({ username, mode });
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

export type AdviceResult = { ok: true; entry: Entry } | { ok: false; error: string };

/**
 * Generate (or regenerate) the AI advice for one goal and one model, and cache it in job_summaries.llm_advice
 * under "<goal>|<model>". The browser only sends ids: the goal and the model are checked against fixed lists here.
 */
export async function generateAdviceAction(jobId: string, goal: string, model: string): Promise<AdviceResult> {
  if (!UUID_RE.test(jobId)) return { ok: false, error: "無效的任務 ID" };
  if (!isGoal(goal)) return { ok: false, error: "無效的目標" };
  if (!isModel(model)) return { ok: false, error: "不支援的模型" };
  if (!llmEnabled()) return { ok: false, error: "尚未設定 LLM_API_KEY" };

  const supabase = await createClient();
  const { data: job } = await supabase.from("jobs").select("username").eq("id", jobId).maybeSingle();
  const { data: summary } = await supabase.from("job_summaries").select("group_analysis").eq("job_id", jobId).maybeSingle();
  if (!job || !summary) return { ok: false, error: "找不到分析結果" };

  let advice;
  try {
    advice = await generateAdvice(model, goal, buildPrompt(job.username, goal, summary), actionCount(goal, summary));
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "產生失敗" };
  }
  const entry: Entry = {
    goal, model, generated_at: new Date().toISOString(), n_posts: summary.group_analysis?.real?.writing_guide?.n_posts ?? 0, basis: adviceBasis(goal, summary), advice,
  };
  // merge into the CURRENT cache (another goal/model may have been stored meanwhile), then save
  const { data: latest } = await supabase.from("job_summaries").select("llm_advice").eq("job_id", jobId).maybeSingle();
  const { data, error } = await supabase
    .from("job_summaries")
    .update({ llm_advice: withEntry(latest?.llm_advice, entry) })
    .eq("job_id", jobId)
    .select("job_id");
  if (error || !data?.length) return { ok: false, error: error?.message ?? "無法儲存建議" };
  revalidatePath(`/dashboard/jobs/${jobId}`);
  return { ok: true, entry };
}
