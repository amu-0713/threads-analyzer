import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-bold">Threads Analyzer</h1>
      <p className="mt-2 text-sm opacity-70">Threads 帳號貼文爬取與數據分析工具</p>
      <Link href="/dashboard" className="mt-6 inline-block underline">
        前往 Dashboard
      </Link>
    </main>
  );
}
