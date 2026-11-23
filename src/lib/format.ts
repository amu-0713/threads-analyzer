export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function pct(x: number | null | undefined, digits = 2): string {
  return x == null ? "—" : `${(x * 100).toFixed(digits)}%`;
}

export function num(x: number | null | undefined, digits = 0): string {
  return x == null ? "—" : x.toLocaleString("zh-TW", { maximumFractionDigits: digits });
}

/** Views are exact below 10,000; Threads shows "x.x 萬" above that, so mark those as approximate. */
export function views(v: number | null | undefined, rounded?: boolean): string {
  return v == null ? "—" : `${rounded ? "≈" : ""}${v.toLocaleString("zh-TW")}`;
}

export function interactionRate(p: { views: number | null; likes: number; replies: number; reposts: number; quotes: number }): number | null {
  return p.views ? (p.likes + p.replies + p.reposts + p.quotes) / p.views : null;
}

export function dateTime(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hourCycle: "h23" }) : "—";
}

/** "2026/11/23 02:07:07" in Taipei time. Built by hand (UTC+8, no DST) because toLocaleString output can differ between the
 *  Node server and the browser (invisible characters), which breaks hydration in client components. */
export function taipeiStamp(iso: string): string {
  const d = new Date(new Date(iso).getTime() + 8 * 3600_000);
  const z = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}/${z(d.getUTCMonth() + 1)}/${z(d.getUTCDate())} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}:${z(d.getUTCSeconds())}`;
}

/** How a job was scraped: logged out (first screen only) or with the owner's own Threads session. */
export function modeLabel(mode: string | null | undefined): string {
  return mode === "login" ? "登入模式" : "未登入";
}

/** A short quote of a post that ends at a sentence end (or a space) instead of in the middle of a word; adds "…" when cut.
 *  Cuts by code point so an emoji is never split (the half character renders differently on server and client). */
export function excerpt(text: string | null | undefined, max = 40): string {
  const chars = Array.from((text ?? "").replace(/\s+/g, " ").trim());
  if (chars.length <= max) return chars.join("") || "（無文字）";
  const head = chars.slice(0, max);
  const lastIndex = (re: RegExp) => head.reduce((acc, c, i) => (re.test(c) ? i : acc), -1);
  const min = Math.floor(max / 3);
  const end = lastIndex(/[。！？!?；;…]/);
  if (end >= min) return head.slice(0, end + 1).join("") + "…";
  const space = lastIndex(/ /);
  if (space >= min) return head.slice(0, space).join("") + "…";
  return head.join("") + "…";
}
