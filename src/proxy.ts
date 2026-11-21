import type { NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/proxy";

export async function proxy(request: NextRequest) {
  const { response, user, redirectTo } = await updateSession(request);
  const { pathname } = request.nextUrl;

  // Protect /dashboard (and everything under it).
  if (!user && pathname.startsWith("/dashboard")) {
    return redirectTo("/login");
  }
  // Already signed in: skip the login page.
  if (user && pathname === "/login") {
    return redirectTo("/dashboard");
  }
  return response;
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
