"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
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
