/**
 * Normalize a Threads username or profile/post URL to a bare lowercase username.
 * Accepts: "name", "@name", "threads.com/@name", "https://www.threads.net/@name/post/abc?x=1"
 * Returns null if the result is not a valid Threads username.
 */
const USERNAME_RE = /^[a-z0-9._]{1,30}$/;

export function normalizeUsername(input: string): string | null {
  let s = input.trim();
  if (!s) return null;

  // URL form: pull out the "@name" path segment.
  const m = s.match(
    /^(?:https?:\/\/)?(?:www\.)?threads\.(?:com|net)\/@([^/?#\s]+)/i,
  );
  if (m) s = m[1];
  else if (/^(?:https?:\/\/)?[^/\s]+\.[^/\s]+\//i.test(s)) return null; // some other URL

  s = s.replace(/^@/, "").toLowerCase();
  return USERNAME_RE.test(s) ? s : null;
}
