import Link from "next/link";
import { deleteJob, rerunJob } from "@/app/dashboard/actions";
import ConfirmButton from "@/components/ConfirmButton";
import PendingCommand from "@/components/PendingCommand";
import { Fragment } from "react";
import { modeLabel } from "@/lib/format";
import { statusLabel } from "@/lib/status";
import type { Job } from "@/lib/types";

export default function JobList({ jobs }: { jobs: Job[] }) {
  if (jobs.length === 0) {
    return <p className="text-sm opacity-60">還沒有任務，從上方新增第一個分析。</p>;
  }
  return (
    <div className="overflow-x-auto">
    <table className="tbl w-full text-left text-sm max-sm:[&_td]:px-1 max-sm:[&_th]:px-1">
      <thead>
        <tr className="border-b border-current/20">
          <th className="py-2">帳號</th>
          <th>模式</th>
          <th>狀態</th>
          <th>貼文數</th>
          <th className="hidden sm:table-cell">建立時間</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <Fragment key={j.id}>
          <tr className="border-b border-current/10">
            <td className="py-2">
              {j.status === "done" ? (
                <Link href={`/dashboard/jobs/${j.id}`} className="underline">@{j.username}</Link>
              ) : (
                <>@{j.username}</>
              )}
            </td>
            <td className="whitespace-nowrap">{modeLabel(j.mode)}</td>
            <td className="whitespace-nowrap">{statusLabel(j.status)}{j.status === "failed" && j.error ? <div className="max-w-xs whitespace-normal text-xs text-red-600">{j.error}</div> : null}</td>
            <td>{j.post_count}</td>
            <td className="hidden sm:table-cell">{new Date(j.created_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei" })}</td>
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
          {j.status === "pending" && (
            <tr className="border-b border-current/10">
              <td colSpan={6} className="pb-3">
                <PendingCommand mode={j.mode} />
              </td>
            </tr>
          )}
          </Fragment>
        ))}
      </tbody>
    </table>
    </div>
  );
}
