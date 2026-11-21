import { login, signup } from "./actions";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; message?: string }>;
}) {
  const { error, message } = await searchParams;

  return (
    <main className="mx-auto w-full max-w-sm p-8">
      <h1 className="text-2xl font-bold">登入 / 註冊</h1>

      {error && <p className="mt-4 rounded bg-red-100 p-2 text-sm text-red-800">{error}</p>}
      {message && <p className="mt-4 rounded bg-green-100 p-2 text-sm text-green-800">{message}</p>}

      <form className="mt-6 flex flex-col gap-3">
        <input
          name="email"
          type="email"
          placeholder="Email"
          required
          autoComplete="email"
          className="rounded border border-current/30 bg-transparent p-2"
        />
        <input
          name="password"
          type="password"
          placeholder="密碼（至少 6 字元）"
          required
          minLength={6}
          autoComplete="current-password"
          className="rounded border border-current/30 bg-transparent p-2"
        />
        <div className="flex gap-2">
          <button formAction={login} className="flex-1 rounded bg-foreground p-2 text-background">
            登入
          </button>
          <button formAction={signup} className="flex-1 rounded border border-current/40 p-2">
            註冊
          </button>
        </div>
      </form>
    </main>
  );
}
