import { interactionRate } from "@/lib/format";
import type { Post } from "@/lib/types";

const COLUMNS = [
  "post_url", "posted_at", "source", "group", "post_type", "views", "views_rounded", "likes", "replies", "reposts",
  "quotes", "interaction_rate", "char_count", "hashtag_count", "mention_count", "url_count", "text",
] as const;

/** One flat record per post. `source` ('real' | 'mock') is always included. */
export function toRecord(p: Post) {
  return {
    post_url: p.post_url,
    posted_at: p.posted_at ? new Date(p.posted_at).toLocaleString("sv-SE", { timeZone: "Asia/Taipei" }).replace(" ", "T") + "+08:00" : null,
    source: p.source,
    group: p.group,
    post_type: p.post_type,
    views: p.views,
    views_rounded: p.views_rounded,
    likes: p.likes,
    replies: p.replies,
    reposts: p.reposts,
    quotes: p.quotes,
    interaction_rate: interactionRate(p),
    char_count: p.char_count,
    hashtag_count: p.hashtag_count,
    mention_count: p.mention_count,
    url_count: p.url_count,
    text: p.text ?? "",
  };
}

function cell(v: unknown): string {
  if (v == null) return "";
  let s = String(v);
  // Spreadsheet formula injection: a text cell must not start with = + - @
  if (typeof v === "string" && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(posts: Post[]): string {
  const rows = posts.map(toRecord);
  const lines = [COLUMNS.join(","), ...rows.map((r) => COLUMNS.map((c) => cell(r[c])).join(","))];
  return "﻿" + lines.join("\r\n") + "\r\n"; // BOM so Excel reads UTF-8
}
