"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

function field(formData: FormData, name: string) {
  return String(formData.get(name) ?? "").trim();
}

/** Supabase returns English messages; show Chinese ones (unknown messages get a generic line instead of English text). */
function zhAuthError(message: string): string {
  const m = message.toLowerCase();
  if (m.includes("invalid login credentials")) return "帳號或密碼錯誤。";
  if (m.includes("email not confirmed")) return "Email 還沒驗證，請先點驗證信裡的連結。";
  if (m.includes("already registered") || m.includes("already been registered")) return "這個 Email 已經註冊過，請直接登入。";
  if (m.includes("at least") && m.includes("character")) return "密碼至少需要 6 個字元。";
  if (m.includes("rate limit") || m.includes("too many")) return "操作太頻繁，請稍後再試。";
  if (m.includes("valid email") || m.includes("invalid email") || m.includes("unable to validate email")) return "請輸入有效的 Email。";
  if (m.includes("fetch failed") || m.includes("network")) return "連線失敗，請稍後再試。";
  return "操作失敗，請稍後再試。";
}

function back(params: Record<string, string>): never {
  redirect(`/login?${new URLSearchParams(params).toString()}`);
}

export async function login(formData: FormData) {
  const supabase = await createClient();
  const { error } = await supabase.auth.signInWithPassword({
    email: field(formData, "email"),
    password: String(formData.get("password") ?? ""),
  });
  if (error) back({ error: zhAuthError(error.message) });
  redirect("/dashboard");
}

export async function signup(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.signUp({
    email: field(formData, "email"),
    password: String(formData.get("password") ?? ""),
  });
  if (error) back({ error: zhAuthError(error.message) });
  // With "Confirm email" enabled there is no session until the link is clicked.
  if (!data.session) back({ message: "註冊成功，請到信箱點擊驗證連結後再登入。" });
  redirect("/dashboard");
}
