// TEMPORARY diagnostic (removed in the next commit): lists the models the API key can use and times one
// advice generation. Login-protected by src/proxy.ts. Never returns the key.
import { NextResponse, type NextRequest } from "next/server";
import { buildPrompt } from "@/lib/llm";
import { createClient } from "@/lib/supabase/server";

export const maxDuration = 120;

export async function GET(request: NextRequest) {
  const key = process.env.LLM_API_KEY;
  if (!key) return NextResponse.json({ error: "LLM_API_KEY not set" }, { status: 500 });
  const sp = request.nextUrl.searchParams;

  if (sp.get("action") === "models") {
    const out: unknown[] = [];
    let pageToken = "";
    for (let i = 0; i < 10; i++) {
      const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models?pageSize=200${pageToken ? `&pageToken=${pageToken}` : ""}`, {
        headers: { "x-goog-api-key": key },
      });
      const j = await r.json();
      if (!r.ok) return NextResponse.json({ status: r.status, error: j?.error?.message ?? j }, { status: 502 });
      for (const m of j.models ?? []) {
        if ((m.supportedGenerationMethods ?? []).includes("generateContent")) {
          out.push({ name: m.name, displayName: m.displayName, version: m.version, thinking: m.thinking, outTokens: m.outputTokenLimit });
        }
      }
      pageToken = j.nextPageToken ?? "";
      if (!pageToken) break;
    }
    return NextResponse.json({ count: out.length, models: out });
  }

  const model = sp.get("model");
  const job = sp.get("job");
  if (!model || !job) return NextResponse.json({ error: "need model & job" }, { status: 400 });
  const thinkingConfig = sp.get("thinking") ? JSON.parse(sp.get("thinking")!) : undefined;

  const supabase = await createClient();
  const [{ data: j }, { data: s }] = await Promise.all([
    supabase.from("jobs").select("username").eq("id", job).maybeSingle(),
    supabase.from("job_summaries").select("metrics, group_analysis, insights").eq("job_id", job).maybeSingle(),
  ]);
  if (!j || !s) return NextResponse.json({ error: "job/summary not found" }, { status: 404 });

  const started = Date.now();
  try {
    const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/${model.startsWith("models/") ? model : `models/${model}`}:generateContent`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": key },
      body: JSON.stringify({
        contents: [{ role: "user", parts: [{ text: buildPrompt(j.username, s) }] }],
        generationConfig: { temperature: 0.4, maxOutputTokens: 4096, ...(thinkingConfig ? { thinkingConfig } : {}) },
      }),
      signal: AbortSignal.timeout(110_000),
    });
    const body = await r.json();
    const cand = body?.candidates?.[0];
    const text: string = (cand?.content?.parts ?? []).filter((p: { thought?: boolean }) => !p.thought).map((p: { text?: string }) => p.text ?? "").join("");
    return NextResponse.json({
      model, thinkingConfig: thinkingConfig ?? null, status: r.status, ms: Date.now() - started, finishReason: cand?.finishReason, chars: text.length,
      usage: body?.usageMetadata, error: r.ok ? undefined : body?.error?.message, head: text.slice(0, 120), tail: text.slice(-80),
    });
  } catch (e) {
    return NextResponse.json({ model, ms: Date.now() - started, error: (e as Error).message }, { status: 504 });
  }
}
