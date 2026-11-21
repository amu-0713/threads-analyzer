import Link from "next/link";
import { deleteJob, rerunJob } from "@/app/dashboard/actions";
import ConfirmButton from "@/components/ConfirmButton";
import { modeLabel } from "@/lib/format";
import type { Job } from "@/lib/types";

export default function JobList({ jobs }: { jobs: Job[] }) {
  if (jobs.length === 0) {
    return <p className="text-sm opacity-60">還沒有任務，從上方新增第一個分析。</p>;
  }
  return (
    <div className="overflow-x-auto">
    <table className="tbl w-full min-w-[520px] text-left text-sm">
      <thead>
        <tr className="border-b border-current/20">
          <th className="py-2">帳號</th>
          <th>模式</th>
          <th>狀態</th>
          <th>貼文數</th>
          <th>建立時間</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id} className="border-b border-current/10">
            <td className="py-2">
              {j.status === "done" ? (
                <Link href={`/dashboard/jobs/${j.id}`} className="underline">@{j.username}</Link>
              ) : (
                <>@{j.username}</>
              )}
            </td>
            <td>{modeLabel(j.mode)}</td>
            <td>{j.status}{j.status === "failed" && j.error ? <div className="max-w-xs text-xs text-red-600">{j.error}</div> : null}</td>
            <td>{j.post_count}</td>
            <td>{new Date(j.created_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei" })}</td>
            <td className="whitespace-nowrap py-1 text-right">
              {(j.status === "done" || j.status === "failed") && (
                <form action={rerunJob} className="inline">
                  <input type="hidden" name="id" value={j.id} />
                  <button className="mr-3 underline">重跑</button>
                </form>
              )}
              <form action={deleteJob} className="inline">
                <input type="hidden" name="id" value={j.id} />
                <ConfirmButton message={`確定刪除 @${j.username} 的任務？貼文與分析結果會一併刪除，無法復原。`} className="text-red-600 underline">
                  刪除
                </ConfirmButton>
              </form>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}
