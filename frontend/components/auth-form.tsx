"use client";
import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Landmark } from "lucide-react";
import { auth } from "@/lib/auth";
import { Button } from "./ui/button";

export function AuthForm({ signup = false }: { signup?: boolean }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    const form = new FormData(event.currentTarget);
    try {
      if (
        process.env.NEXT_PUBLIC_TEST_MODE === "true" &&
        form.get("test_token")
      ) {
        sessionStorage.setItem(
          "creatorops-test-token",
          String(form.get("test_token")),
        );
        router.push("/dashboard");
        return;
      }
      const credentials = {
        email: String(form.get("email")),
        password: String(form.get("password")),
      };
      const result = signup
        ? await auth().auth.signUp({
            ...credentials,
            options: {
              data: { name: String(form.get("name")) },
              emailRedirectTo: `${window.location.origin}/login`,
            },
          })
        : await auth().auth.signInWithPassword(credentials);
      if (result.error) throw result.error;
      if (signup && !result.data.session)
        setMessage("Check your email to confirm your account, then sign in.");
      else router.push("/dashboard");
    } catch (error) {
      setError(error instanceof Error ? error.message : "Sign in failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="flex min-h-screen items-center justify-center p-5">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-9 shadow-sm">
        <div className="mb-9 flex items-center gap-3 font-semibold">
          <span className="rounded-lg bg-teal-800 p-2 text-white">
            <Landmark size={22} />
          </span>
          CreatorOps <span className="text-teal-700">AI</span>
        </div>
        <h1 className="text-2xl font-semibold">
          {signup ? "Create your account" : "Welcome back"}
        </h1>
        <p className="mb-7 mt-2 text-sm text-slate-500">
          Your agency’s financial operations, in one workspace.
        </p>
        <form onSubmit={submit} className="grid gap-5">
          {process.env.NEXT_PUBLIC_TEST_MODE === "true" ? (
            <label>
              Test session token
              <textarea name="test_token" required rows={3} />
            </label>
          ) : (
            <>
              {signup && (
                <label>
                  Name
                  <input
                    name="name"
                    required
                    maxLength={160}
                    autoComplete="name"
                  />
                </label>
              )}
              <label>
                Email
                <input
                  name="email"
                  type="email"
                  required
                  autoComplete="email"
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  required
                  minLength={12}
                  autoComplete={signup ? "new-password" : "current-password"}
                />
              </label>
            </>
          )}
          {error && (
            <p
              role="alert"
              className="rounded-md bg-red-50 p-3 text-sm text-red-800"
            >
              {error}
            </p>
          )}
          {message && (
            <p
              role="status"
              className="rounded-md bg-teal-50 p-3 text-sm text-teal-800"
            >
              {message}
            </p>
          )}
          <Button disabled={busy}>
            {busy ? "Signing in…" : signup ? "Create account" : "Sign in"}
          </Button>
        </form>
        <p className="mt-6 text-sm text-slate-500">
          {signup ? "Already have an account?" : "New to CreatorOps?"}{" "}
          <Link
            className="font-medium text-teal-800"
            href={signup ? "/login" : "/signup"}
          >
            {signup ? "Sign in" : "Create account"}
          </Link>
        </p>
      </section>
    </main>
  );
}
