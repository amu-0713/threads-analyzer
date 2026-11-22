"use client";

import { useState } from "react";
import type { JobMode } from "@/lib/types";

export function commandFor(mode: JobMode): string {
  return mode === "login" ? "python -m src.pipeline.run --login --pending" : "python -m src.pipeline.run --pending";
}

/** What to run on your own computer for a pending job, with a copy button. */
export default function PendingCommand({ mode }: { mode: JobMode }) {
  const [copied, setCopied] = useState(false);
  const cmd = commandFor(mode);

  async function copy() {
    try {
      await navigator.clipboard.writeText(cmd);
    } catch {
      const ta = document.createElement("textarea"); // clipboard API unavailable (http / old browser)
      ta.value = cmd;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="rounded border border-current/20 p-3 text-sm">
      <p className="text-xs opacity-70">爬取在本機執行，執行後重新整理頁面即可看到結果。</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <code className="min-w-0 flex-1 break-all rounded bg-current/10 px-2 py-1 text-xs">{cmd}</code>
        <button type="button" onClick={copy} className="whitespace-nowrap rounded border border-current/30 px-3 py-1 text-xs" aria-live="polite">
          {copied ? "已複製" : "複製"}
        </button>
      </div>
    </div>
  );
}
