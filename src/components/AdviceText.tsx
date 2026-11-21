import { Fragment } from "react";

/**
 * Renders LLM text safely: a tiny Markdown subset (**bold**, "-"/"*" bullets, "#" headings) turned into React
 * elements. No dangerouslySetInnerHTML, so model output can never inject HTML.
 */
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part.replace(/[*`]/g, "")}</Fragment>,
  );
}

export default function AdviceText({ text }: { text: string }) {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  return (
    <div className="space-y-2">
      {lines.map((l, i) => (
        <p key={i}>{inline(l.replace(/^#{1,6}\s*/, "").replace(/^[*•-]\s+/, ""))}</p>
      ))}
    </div>
  );
}
