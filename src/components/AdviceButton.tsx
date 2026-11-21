"use client";

import { useFormStatus } from "react-dom";

/** Submit button for the AI-advice form: disabled and labelled "產生中…" while the server action runs. */
export default function AdviceButton({ enabled, hasAdvice }: { enabled: boolean; hasAdvice: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button
      disabled={!enabled || pending}
      aria-busy={pending}
      className="rounded bg-foreground px-4 py-2 text-background disabled:cursor-not-allowed disabled:opacity-40"
    >
      {pending ? "產生中…" : hasAdvice ? "重新產生 AI 建議" : "產生 AI 建議"}
    </button>
  );
}
