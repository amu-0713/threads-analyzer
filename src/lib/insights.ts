import fs from "node:fs";
import path from "node:path";
import { marked } from "marked";

/** reports/insights.md -> HTML. The file lives in this repo (trusted content), so no sanitising step. */
export function insightsHtml(): string | null {
  try {
    const md = fs.readFileSync(path.join(process.cwd(), "reports", "insights.md"), "utf8");
    return marked.parse(md, { async: false, gfm: true }) as string;
  } catch {
    return null;
  }
}
