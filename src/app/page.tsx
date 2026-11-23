import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-2xl font-bold">Threads Analyzer</h1>
      <p className="mt-2 text-sm opacity-70">Threads 帳號貼文爬取與數據分析工具</p>
      <p className="mt-4 text-sm leading-relaxed">
        輸入一個 Threads 帳號，收集它的公開貼文，依按讚與回覆分成共鳴型、討論型、低迷型三組，列出前後期一致的寫法，再用 AI 依目標（提高按讚、帶動討論）建議下一篇貼文怎麼寫。樣本有限，結果只能當參考，不能做統計推論。
      </p>
      <Link href="/dashboard" className="mt-6 inline-block underline">
        前往 Dashboard
      </Link>
    </main>
  );
}
