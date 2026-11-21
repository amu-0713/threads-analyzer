// Descriptive observations for the report page. Pure functions: medians, counts and direction only.
// No p-values and no inferential wording (the sample is 5-9 posts per account).
import type { Post } from "@/lib/types";

const ir = (p: Post) => (p.views ? (p.likes + p.replies + p.reposts + p.quotes) / p.views : 0);
const lr = (p: Post) => (p.views ? p.likes / p.views : 0);
const rr = (p: Post) => (p.views ? p.replies / p.views : 0);

function median(xs: number[]): number {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
const pc = (x: number, d = 2) => (Number.isNaN(x) ? "—" : `${(x * 100).toFixed(d)}%`);
const hourTaipei = (iso: string) => Number(new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Taipei", hour: "2-digit", hour12: false })) % 24;
const dayKey = (iso: string) => new Date(iso).toLocaleDateString("zh-TW", { timeZone: "Asia/Taipei", month: "numeric", day: "numeric" });

function direction(a: number, b: number, nameA: string): string {
  if (Number.isNaN(a) || Number.isNaN(b)) return "其中一組沒有貼文，無法比較";
  if (Math.abs(a - b) < 1e-9) return "兩組相同";
  return a > b ? `${nameA}較高` : `${nameA}較低`;
}

/** The three comparisons shown under "觀察" in the real-only view. */
export function describePatterns(posts: Post[]): string[] {
  const rated = posts.filter((p) => p.views);
  const cmp = (title: string, nameA: string, nameB: string, pred: (p: Post) => boolean, metric: (p: Post) => number, metricName: string) => {
    const a = rated.filter(pred), b = rated.filter((p) => !pred(p));
    const small = a.length < 3 || b.length < 3 ? "（有一組不到 3 篇，只能看個大概）" : "";
    return `${title}：${nameA} ${a.length} 篇，${metricName}中位數 ${pc(median(a.map(metric)))}；${nameB} ${b.length} 篇，${pc(median(b.map(metric)))}。方向：${direction(median(a.map(metric)), median(b.map(metric)), nameA)}${small}。`;
  };
  return [
    cmp("提問句 vs 其他貼文", "提問句", "其他貼文", (p) => /[？?]/.test((p.text ?? "").replace(/https?:\/\/\S+/g, " ")), rr, "回覆率"),
    cmp("晚間（18–23 點）vs 其他時段", "晚間貼文", "其他時段貼文", (p) => !!p.posted_at && hourTaipei(p.posted_at) >= 18, lr, "按讚率"),
    cmp("含連結 vs 無連結", "含連結貼文", "無連結貼文", (p) => p.url_count > 0, ir, "互動率"),
  ];
}

type Threaded = Post & { followUp: boolean };

/** Same account, <= 5 minutes after the previous post = a follow-up in the same thread. */
function markThreads(posts: Post[]): Threaded[] {
  const sorted = [...posts].filter((p) => p.posted_at).sort((a, b) => +new Date(a.posted_at!) - +new Date(b.posted_at!));
  return sorted.map((p, i) => ({ ...p, followUp: i > 0 && +new Date(p.posted_at!) - +new Date(sorted[i - 1].posted_at!) <= 5 * 60_000 }));
}

/**
 * "本帳號內容觀察": descriptive notes from THIS account's real posts only (mock rows are dropped here).
 * Always returns at least 3 notes when the account has 3+ real posts with views.
 */
export function accountNotes(all: Post[]): string[] {
  const real = all.filter((p) => p.source === "real" && p.views && p.posted_at);
  if (real.length < 3) return [];
  const th = markThreads(real);
  const notes: string[] = [];
  const medLen = median(real.map((p) => p.char_count));

  // 1. what the highest-interaction posts have in common
  const top = [...th].sort((a, b) => ir(b) - ir(a)).slice(0, 3);
  const types = Object.entries(top.reduce<Record<string, number>>((m, p) => ((m[p.post_type ?? "未分類"] = (m[p.post_type ?? "未分類"] ?? 0) + 1), m), {}))
    .map(([t, n]) => `${t} ${n} 篇`).join("、");
  const lens = top.map((p) => p.char_count);
  const openers = top.filter((p) => !p.followUp).length;
  const evening = top.filter((p) => hourTaipei(p.posted_at!) >= 18).length;
  notes.push(
    `互動率最高的 3 篇（${top.map((p) => pc(ir(p))).join("、")}）：字數 ${Math.min(...lens)}–${Math.max(...lens)}（本帳號中位數 ${Math.round(medLen)}）；類型：${types}；` +
      `${openers} 篇是單篇或串文首篇；${evening} 篇發在晚間 18–23 點。`,
  );

  // 2. post types
  const byType = real.reduce<Record<string, Post[]>>((m, p) => ((m[p.post_type ?? "未分類"] ??= []).push(p), m), {});
  const typeRows = Object.entries(byType).map(([t, ps]) => ({ t, n: ps.length, m: median(ps.map(ir)) })).sort((a, b) => b.n - a.n);
  if (typeRows.length === 1) notes.push(`貼文類型：${real.length} 篇全部是${typeRows[0].t}，沒有其他類型可以比較。`);
  else {
    const best = [...typeRows].sort((a, b) => b.m - a.m)[0];
    notes.push(`貼文類型：${typeRows.map((r) => `${r.t} ${r.n} 篇（互動率中位數 ${pc(r.m)}）`).join("、")}；中位數最高的是${best.t}${best.n < 3 ? `（只有 ${best.n} 篇）` : ""}。`);
  }

  // 3. thread opener vs follow-ups
  const follow = th.filter((p) => p.followUp);
  if (!follow.length) notes.push("串文：沒有 5 分鐘內連發的貼文，無法比較串文首篇與續篇。");
  else {
    const idx = new Map(th.map((p, i) => [p.id, i]));
    const pairs = follow.map((f) => {
      let i = idx.get(f.id)!;
      while (i > 0 && th[i].followUp) i--; // walk back to the opener
      return { o: th[i], f };
    });
    const lowerViews = pairs.filter(({ o, f }) => (f.views ?? 0) < (o.views ?? 0)).length;
    const lowerLikes = pairs.filter(({ o, f }) => lr(f) < lr(o)).length;
    notes.push(
      `串文首篇 vs 續篇：${new Set(pairs.map((p) => p.o.id)).size} 個串文共 ${follow.length} 篇續篇；續篇觀看低於首篇的有 ${lowerViews} 篇` +
        `（續篇 ÷ 首篇的觀看比，中位數 ${median(pairs.map(({ o, f }) => (f.views ?? 0) / (o.views ?? 1))).toFixed(2)}），按讚率低於首篇的有 ${lowerLikes} 篇。`,
    );
  }

  // 4. most-viewed post (and how old it is)
  const mv = [...real].sort((a, b) => (b.views ?? 0) - (a.views ?? 0))[0];
  const newest = Math.max(...real.map((p) => +new Date(p.posted_at!)));
  const ageDays = Math.round((newest - +new Date(mv.posted_at!)) / 86_400_000);
  notes.push(
    `觀看最高的貼文：${dayKey(mv.posted_at!)} 發，${mv.views_rounded ? "≈" : ""}${mv.views!.toLocaleString("zh-TW")} 次（本帳號觀看中位數 ${Math.round(median(real.map((p) => p.views!))).toLocaleString("zh-TW")}）` +
      (ageDays >= 14 ? `；它比本帳號最新的貼文早 ${ageDays} 天，累積觀看的時間較長，不適合和近期貼文直接比較。` : "，與最新貼文發在同一段時間。"),
  );

  // 5. shorter vs longer posts
  if (real.length >= 4) {
    const short = real.filter((p) => p.char_count <= medLen), long = real.filter((p) => p.char_count > medLen);
    if (short.length && long.length)
      notes.push(`字數：不超過中位數（${Math.round(medLen)} 字）的 ${short.length} 篇，按讚率中位數 ${pc(median(short.map(lr)))}；較長的 ${long.length} 篇 ${pc(median(long.map(lr)))}。`);
  }
  return notes;
}
