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

/** How a job was scraped: logged out (first screen only) or with the owner's own Threads session. */
export function modeLabel(mode: string | null | undefined): string {
  return mode === "login" ? "登入模式" : "未登入";
}
