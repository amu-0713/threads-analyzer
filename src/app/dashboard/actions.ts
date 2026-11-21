"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { UUID_RE } from "@/lib/format";
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
