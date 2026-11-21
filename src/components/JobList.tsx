export type Job = {
  id: string;
  username: string;
  status: "pending" | "scraping" | "analyzing" | "done" | "failed";
  post_count: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
};

export default function JobList({ jobs }: { jobs: Job[] }) {
  if (jobs.length === 0) {
    return <p className="text-sm opacity-60">還沒有任務，從上方新增第一個分析。</p>;
  }
  return (
    <table className="w-full text-left text-sm">
      <thead>
        <tr className="border-b border-current/20">
          <th className="py-2">帳號</th>
          <th>狀態</th>
          <th>貼文數</th>
          <th>建立時間</th>
        </tr>
      </thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id} className="border-b border-current/10">
            <td className="py-2">@{j.username}</td>
            <td>{j.status}</td>
            <td>{j.post_count}</td>
            <td>{new Date(j.created_at).toLocaleString("zh-TW", { timeZone: "Asia/Taipei" })}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
