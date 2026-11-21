"use server";

import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

function field(formData: FormData, name: string) {
  return String(formData.get(name) ?? "").trim();
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
  if (error) back({ error: error.message });
  redirect("/dashboard");
}

export async function signup(formData: FormData) {
  const supabase = await createClient();
  const { data, error } = await supabase.auth.signUp({
    email: field(formData, "email"),
    password: String(formData.get("password") ?? ""),
  });
  if (error) back({ error: error.message });
  // With "Confirm email" enabled there is no session until the link is clicked.
  if (!data.session) back({ message: "註冊成功，請到信箱點擊驗證連結後再登入。" });
  redirect("/dashboard");
}
