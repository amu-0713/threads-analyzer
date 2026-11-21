import { createClient } from "@/lib/supabase/server";
import Link from "next/link";
import JobList from "@/components/JobList";
import type { Job } from "@/lib/types";
import NewJobForm from "@/components/NewJobForm";

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; notice?: string }>;
}) {
  const { error, notice } = await searchParams;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // RLS limits this to the signed-in user's own jobs.
  const { data: jobs, error: loadError } = await supabase
    .from("jobs")
    .select("id, username, status, post_count, error, created_at, finished_at")
    .order("created_at", { ascending: false });

  return (
    <main className="mx-auto w-full max-w-3xl p-8">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <form action="/auth/signout" method="post" className="flex items-center gap-3 text-sm">
          <span className="opacity-70">{user?.email}</span>
          <button className="underline">登出</button>
        </form>
      </header>

      <section className="mt-6">
        <h2 className="mb-2 font-semibold">新增分析</h2>
        <NewJobForm />
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        {notice && <p className="mt-2 text-sm text-green-700">{notice}</p>}
      </section>

      <section className="mt-8">
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="font-semibold">任務列表</h2>
          <Link href="/dashboard/compare" className="text-sm underline">多帳號比較</Link>
        </div>
        {loadError ? (
          <p className="text-sm text-red-600">載入失敗：{loadError.message}</p>
        ) : (
          <JobList jobs={(jobs ?? []) as Job[]} />
        )}
      </section>
    </main>
  );
}
