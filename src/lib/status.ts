/** Job status as shown to people (the database keeps the English values). */
const LABELS: Record<string, string> = { pending: "等待中", scraping: "爬取中", analyzing: "分析中", done: "完成", failed: "失敗" };
export const statusLabel = (status: string) => LABELS[status] ?? status;
