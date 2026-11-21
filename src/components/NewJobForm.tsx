import { createJob } from "@/app/dashboard/actions";

export default function NewJobForm() {
  return (
    <form action={createJob} className="space-y-2">
      <div className="flex gap-2">
        <input
          name="target"
          required
          placeholder="帳號或網址，例如 @7eleventw 或 https://www.threads.com/@7eleventw"
          className="min-w-0 flex-1 rounded border border-current/30 bg-transparent p-2"
        />
        <button className="whitespace-nowrap rounded bg-foreground px-4 py-2 text-background">新增分析</button>
      </div>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        <span className="opacity-70">抓取模式</span>
        <select name="mode" defaultValue="anonymous" className="rounded border border-current/30 bg-transparent p-1">
          <option value="anonymous">未登入（只看得到個人頁首屏，約 5–9 篇）</option>
          <option value="login">登入模式（最多 40 篇；需在本機登入後用 --login 執行）</option>
        </select>
      </label>
    </form>
  );
}
