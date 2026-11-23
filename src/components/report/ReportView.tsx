import Link from "next/link";
import WritingGuide from "@/components/report/WritingGuide";
import LengthScatter, { type Pt } from "@/components/charts/LengthScatter";
import TimeSlotChart from "@/components/charts/TimeSlotChart";
import { dateTime, interactionRate, num, pct, views } from "@/lib/format";
import { accountNotes, describePatterns } from "@/lib/observations";
import type { BriefPost, GroupAnalysis, GroupName, JobMode, Metrics, Post, Profile, Scope, Summary } from "@/lib/types";

const GROUP_INFO: Record<GroupName, string> = {
  低迷型: "按讚率與回覆率的帳號內百分位都低於 0.5",
  討論型: "回覆率百分位 ≥ 0.5，且不低於按讚率百分位",
  共鳴型: "按讚率百分位 ≥ 0.5，且高於回覆率百分位",
};

export function SourceBadge({ source }: { source: "real" | "mock" }) {
  return source === "mock" ? (
    <span className="whitespace-nowrap rounded border border-[var(--series-2)] px-1.5 py-0.5 text-xs text-[var(--series-2)]">模擬 mock</span>
  ) : (
    <span className="whitespace-nowrap rounded border border-current/30 px-1.5 py-0.5 text-xs opacity-70">真實</span>
  );
}

function Section({ title, children, id }: { title: string; children: React.ReactNode; id?: string }) {
  return (
    <section id={id} className="mt-10">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded border border-current/20 p-3">
      <div className="text-xs opacity-60">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs opacity-60">{sub}</div>}
    </div>
  );
}

function Snippet({ p }: { p: { text: string | null; post_url: string; source: "real" | "mock" } }) {
  // cut by code point (not UTF-16 unit): slice() can split an emoji in half, and the half renders differently on server and client
  const text = Array.from((p.text ?? "").replace(/\s+/g, " ")).slice(0, 60).join("") || "（無文字）";
  return p.source === "real" ? (
    <a href={p.post_url} target="_blank" rel="noreferrer" className="underline">{text}</a>
  ) : (
    <span>{text}</span>
  );
}

/** `mockTotal` = mock posts of the whole job; `metrics` only counts what the current scope shows (0 mock in the real-only view). */
export function LimitsNotice({ metrics, scope, mode, mockTotal }: { metrics: Metrics; scope: Scope; mode: JobMode; mockTotal: number }) {
  return (
    <aside className="mt-6 rounded border border-current/30 bg-current/5 p-4 text-sm">
      <div className="font-semibold">資料限制</div>
      <ul className="mt-2 list-disc space-y-1 pl-5">
        {mode === "login" ? (
          <li>
            <b>登入模式</b>：這個任務是用資料擁有者<b>自己的 Threads 登入工作階段</b>，在本機捲動個人頁（最多 40 篇）再逐篇開單篇頁取得，
            真實貼文共 <b>{metrics.n_real}</b> 篇。抓取量仍有上限，而且不是「最近 N 篇」（個人頁可能夾帶較舊的置頂貼文）。
          </li>
        ) : (
          <li>
            真實貼文只有 <b>{metrics.n_real}</b> 篇：未登入的 Threads 只提供個人頁首屏（約 5–9 篇），本工具在未登入模式下不登入也不繞過登入牆，
            所以樣本很少，百分位、分組與比較都只能當參考。
          </li>
        )}
        <li>觀看數取自單篇頁；≥ 1 萬時 Threads 只顯示到千位（如「1.5 萬」），以 <b>≈</b> 標示，比率有些微誤差。</li>
        {mockTotal > 0 ? (
          scope === "all" ? (
            <li>
              目前顯示「全部資料」：另含 <b>{mockTotal}</b> 篇<b>模擬貼文（mock）</b>，
              是為了補足到 30 篇而人工產生，不代表帳號真實表現；表格中以「模擬 mock」標示。
            </li>
          ) : (
            <li>
              目前只顯示真實資料；這個任務另有 <b>{mockTotal}</b> 篇<b>模擬貼文（mock）</b>（為了補足到 30 篇而人工產生）已隱藏。
              切換到「全部資料」可以看到，表格中會以「模擬 mock」標示。
            </li>
          )
        ) : (
          <li>此任務沒有補 mock，所有資料都是真實貼文。</li>
        )}
      </ul>
    </aside>
  );
}

function ProfileBox({ p }: { p: Profile }) {
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      <dt className="opacity-60">平均字數</dt><dd>{num(p.avg_char_count, 0)}</dd>
      <dt className="opacity-60">平均按讚率 / 回覆率</dt><dd>{pct(p.avg_like_rate)} / {pct(p.avg_reply_rate)}</dd>
      <dt className="opacity-60">關鍵字</dt><dd>{p.keywords.map((k) => k.word).join("、") || "—"}</dd>
      <dt className="opacity-60">類型</dt><dd>{p.post_types.map((t) => `${t.type} ${t.n}`).join("、") || "—"}</dd>
      <dt className="opacity-60">提問 / 晚間 / 含連結</dt>
      <dd>{pct(p.question_share, 0)} / {pct(p.evening_share, 0)} / {pct(p.link_share, 0)}</dd>
    </dl>
  );
}

function Groups({ ga }: { ga: GroupAnalysis }) {
  return (
    <>
      <p className="mb-3 text-sm opacity-70">
        觀看低於帳號中位數（{num(ga.median_views)}）20% 的貼文不分組，共 {ga.counts["未分組"] ?? 0} 篇。
        每組取最典型的 3–5 篇作為代表貼文（討論型取回覆百分位最高、共鳴型取按讚百分位最高、低迷型取兩者最低），用同一套方法比較。
      </p>
      <div className="grid gap-4 md:grid-cols-3">
        {(Object.keys(GROUP_INFO) as GroupName[]).map((g) => {
          const grp = ga.groups[g];
          return (
            <div key={g} className="rounded border border-current/20 p-3">
              <div className="flex items-baseline justify-between">
                <h3 className="font-semibold">{g}</h3>
                <span className="text-sm opacity-70">{grp.n_members} 篇</span>
              </div>
              <p className="mt-1 text-xs opacity-60">{GROUP_INFO[g]}</p>
              {grp.representatives.length === 0 ? (
                <p className="mt-3 text-sm opacity-60">這組沒有貼文。</p>
              ) : (
                <>
                  <ul className="mt-3 space-y-2 text-sm">
                    {grp.representatives.map((r: BriefPost) => (
                      <li key={r.post_url} className="border-t border-current/10 pt-2">
                        <div className="flex items-center gap-2"><SourceBadge source={r.source} /><span className="text-xs opacity-60">{r.post_type}</span></div>
                        <div className="mt-1"><Snippet p={r} /></div>
                        <div className="mt-0.5 text-xs opacity-60">
                          讚 {num(r.likes)}・回覆 {num(r.replies)}・觀看 {views(r.views, r.views_rounded)}
                          {r.like_pct != null && <>・百分位 讚 {r.like_pct} / 回覆 {r.reply_pct}</>}
                        </div>
                      </li>
                    ))}
                  </ul>
                  {grp.profile_of_representatives && (
                    <div className="mt-3 border-t border-current/10 pt-2">
                      <div className="text-xs font-semibold">代表貼文的共同點（{grp.profile_of_representatives.n} 篇）</div>
                      <ProfileBox p={grp.profile_of_representatives} />
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

export default function ReportView({ summary, posts, scope, mode, advice }: { summary: Summary; posts: Post[]; scope: Scope; mode: JobMode; advice?: React.ReactNode }) {
  const m = summary.metrics[scope];
  const top = summary.top_posts[scope] ?? [];
  const ga = summary.group_analysis[scope];
  const insights = summary.insights[scope] ?? [];
  if (!m) return <p className="mt-6 text-sm opacity-70">這個範圍沒有資料。</p>;

  const scoped = scope === "real" ? posts.filter((p) => p.source === "real") : posts;
  const points: Pt[] = scoped.flatMap((p) => {
    const r = interactionRate(p);
    return r == null ? [] : [{ x: p.char_count, y: +(r * 100).toFixed(3), url: p.post_url, source: p.source }];
  });
  const td = m.time_distribution;
  const notes = accountNotes(posts);
  const realCount = posts.filter((p) => p.source === "real").length;
  const groupOf = (p: Post) => (ga?.assignments[p.post_url] ?? "—");

  return (
    <>
      <LimitsNotice metrics={m} scope={scope} mode={mode} mockTotal={summary.metrics.all?.n_mock ?? 0} />

      <Section title="總覽">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Card label="貼文數" value={String(m.n_posts)} sub={`真實 ${m.n_real}${m.n_mock ? ` + 模擬 ${m.n_mock}` : ""}`} />
          <Card label="平均讚" value={num(m.avg.likes, 1)} sub={`中位數 ${num(m.median.likes)}`} />
          <Card label="平均回覆" value={num(m.avg.replies, 1)} sub={`中位數 ${num(m.median.replies)}`} />
          <Card label="平均轉發" value={num(m.avg.reposts, 1)} sub={`中位數 ${num(m.median.reposts)}`} />
          <Card label="平均觀看" value={num(m.avg.views)} />
          <Card label="平均互動率" value={pct(m.avg_interaction_rate)} sub="(讚+回覆+轉發+引用)÷觀看" />
        </div>
      </Section>

      <Section title="互動率 Top 5">
        <div className="overflow-x-auto">
          <table className="tbl w-full min-w-[560px] text-left text-sm">
            <thead><tr className="border-b border-current/20"><th className="py-2 pr-2">#</th><th>貼文</th><th>來源</th><th className="text-right">觀看</th><th className="text-right">讚</th><th className="text-right">回覆</th><th className="text-right">互動率</th></tr></thead>
            <tbody>
              {top.map((p, i) => (
                <tr key={p.post_url} className="border-b border-current/10 align-top">
                  <td className="py-2 pr-2">{i + 1}</td>
                  <td className="pr-2"><Snippet p={p} /></td>
                  <td><SourceBadge source={p.source} /></td>
                  <td className="text-right tabular-nums">{views(p.views, p.views_rounded)}</td>
                  <td className="text-right tabular-nums">{num(p.likes)}</td>
                  <td className="text-right tabular-nums">{num(p.replies)}</td>
                  <td className="text-right tabular-nums">{pct(p.interaction_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="發文時段分布（台北時間）">
        <TimeSlotChart dist={td} />
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer opacity-70">表格版本</summary>
          <div className="mt-2 overflow-x-auto">
            <table className="text-left text-xs"><thead><tr><th className="pr-3 py-1"></th>{td.slots.map((s) => <th key={s} className="pr-3">{s}</th>)}</tr></thead>
              <tbody>{td.weekdays.map((d, i) => <tr key={d}><td className="pr-3 py-1">{d}</td>{td.counts[i].map((c, j) => <td key={j} className="pr-3 tabular-nums">{c}</td>)}</tr>)}</tbody></table>
          </div>
        </details>
      </Section>

      <Section title="文長 vs 互動率">
        <LengthScatter points={points} />
        <div className="mt-2 overflow-x-auto">
          <table className="text-left text-sm">
            <thead><tr className="border-b border-current/20"><th className="py-1 pr-4">字數</th><th className="pr-4">篇數</th><th>平均互動率</th></tr></thead>
            <tbody>{m.length_vs_interaction.bins.map((b) => <tr key={b.label}><td className="py-1 pr-4">{b.label}</td><td className="pr-4">{b.n}</td><td>{pct(b.avg_interaction_rate)}</td></tr>)}</tbody>
          </table>
        </div>
        <p className="mt-1 text-xs opacity-60">Spearman 相關係數：{m.length_vs_interaction.spearman ?? "—"}（樣本少時不穩定）</p>
      </Section>

      <Section title="關鍵字、hashtag 與貼文類型">
        <div className="grid gap-4 md:grid-cols-3 text-sm">
          <div><div className="mb-1 font-medium">常見關鍵字（含該詞的貼文數）</div>{m.keywords.map((k) => <span key={k.word} className="mr-2 inline-block">{k.word} <span className="opacity-60">{k.posts}</span></span>)}</div>
          <div><div className="mb-1 font-medium">常見 hashtag</div>{m.hashtags.length ? m.hashtags.map((h) => <span key={h.tag} className="mr-2 inline-block">{h.tag} <span className="opacity-60">{h.count}</span></span>) : <span className="opacity-60">沒有 hashtag</span>}</div>
          <div><div className="mb-1 font-medium">貼文類型</div>{m.post_types.map((t) => <div key={t.type}>{t.type}：{t.n} 篇（{pct(t.share, 0)}），平均互動率 {pct(t.avg_interaction_rate)}</div>)}</div>
        </div>
      </Section>

      <Section title="三組分類" id="groups">{ga ? <Groups ga={ga} /> : <p className="text-sm opacity-70">沒有分組結果。</p>}</Section>

      <Section title="寫作清單（僅真實資料）" id="writing-guide">
        <WritingGuide guide={summary.group_analysis.real?.writing_guide} />
      </Section>

      {advice && <Section title="AI 建議" id="ai-advice">{advice}</Section>}

      <Section title="觀察">
        {scope === "real" || m.n_mock === 0 ? (  // no mock rows -> all data IS real data: same descriptive-only view
          <>
            <p className="mb-2 text-xs opacity-70">{m.n_mock === 0 ? "此任務全部是真實資料，" : "僅真實資料，"}只列描述性結果（篇數、中位數、方向）。</p>
            <ul className="list-disc space-y-1 pl-5 text-sm">{describePatterns(scoped).map((t) => <li key={t}>{t}</li>)}</ul>
            <p className="mt-2 text-xs opacity-70">{m.n_real < 30 ? "樣本太小" : "樣本有限"}（真實貼文 {m.n_real} 篇），以上只是描述這批貼文的樣子，不能推論到帳號的一般表現。</p>
          </>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {insights.map((i) => <li key={i.key}>（含 mock，僅用於驗證分析流程）{i.text}</li>)}
          </ul>
        )}
      </Section>

      {notes.length > 0 && (
        <Section title="本帳號內容觀察" id="account-notes">
          <p className="mb-2 text-xs opacity-70">只用這個帳號的 {realCount} 篇真實貼文整理（不含 mock，與上方切換無關），僅描述，供參考。</p>
          <ul className="list-disc space-y-1.5 pl-5 text-sm">{notes.map((t) => <li key={t}>{t}</li>)}</ul>
          <p className="mt-3 text-sm">
            跨 4 個帳號的完整洞察與內容建議，見 <Link href="/dashboard/compare#insights" className="underline">比較頁的「洞察與內容建議」</Link>。
          </p>
        </Section>
      )}

      <Section title={`全部貼文（${scoped.length}）`}>
        <div className="overflow-x-auto">
          <table className="tbl w-full min-w-[720px] text-left text-sm">
            <thead><tr className="border-b border-current/20"><th className="py-2 pr-2">時間</th><th>內容</th><th>來源</th><th>組別</th><th className="text-right">觀看</th><th className="text-right">讚</th><th className="text-right">回覆</th><th className="text-right">轉發</th><th className="text-right">引用</th></tr></thead>
            <tbody>
              {scoped.map((p) => (
                <tr key={p.id} className={`border-b border-current/10 align-top ${p.source === "mock" ? "bg-[var(--series-2)]/10" : ""}`}>
                  <td className="py-2 pr-2 whitespace-nowrap text-xs">{dateTime(p.posted_at)}</td>
                  <td className="pr-2"><Snippet p={p} /></td>
                  <td><SourceBadge source={p.source} /></td>
                  <td className="whitespace-nowrap">{groupOf(p)}</td>
                  <td className="text-right tabular-nums">{views(p.views, p.views_rounded)}</td>
                  <td className="text-right tabular-nums">{num(p.likes)}</td>
                  <td className="text-right tabular-nums">{num(p.replies)}</td>
                  <td className="text-right tabular-nums">{num(p.reposts)}</td>
                  <td className="text-right tabular-nums">{num(p.quotes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
      <p className="mt-8 text-xs opacity-50">分析更新於 {dateTime(summary.updated_at)}・<Link href="/dashboard" className="underline">回任務列表</Link></p>
    </>
  );
}
