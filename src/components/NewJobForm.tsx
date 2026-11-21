import { createJob } from "@/app/dashboard/actions";

export default function NewJobForm() {
  return (
    <form action={createJob} className="flex gap-2">
      <input
        name="target"
        required
        placeholder="帳號或網址，例如 @7eleventw 或 https://www.threads.com/@7eleventw"
        className="flex-1 rounded border border-current/30 bg-transparent p-2"
      />
      <button className="rounded bg-foreground px-4 py-2 text-background">新增分析</button>
    </form>
  );
}
