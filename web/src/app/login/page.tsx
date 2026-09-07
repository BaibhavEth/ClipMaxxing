"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";

import { SiteHeader } from "@/components/site-header";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState<"email" | "google" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const supabase = createClient();

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("error") === "auth_callback") {
      setMessage("Sign-in did not finish. Try again.");
    }
  }, []);

  function callbackUrl() {
    const next = new URLSearchParams(window.location.search).get("next") ?? "/history";
    return `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`;
  }

  async function handleEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading("email");
    setMessage(null);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: { emailRedirectTo: callbackUrl() },
    });
    setLoading(null);
    setMessage(
      error ? error.message : "Check your email for a secure sign-in link.",
    );
  }

  async function handleGoogle() {
    setLoading("google");
    setMessage(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callbackUrl() },
    });
    if (error) {
      setLoading(null);
      setMessage(error.message);
    }
  }

  return (
    <div className="auth-page">
      <SiteHeader account={false} />
      <main className="auth-main">
        <section className="auth-card">
          <div className="auth-heading">
            <span>ClipCraft account</span>
            <h1>Sign in to your workspace</h1>
            <p>Keep your projects, clips, and OpenAI configuration in one place.</p>
          </div>

          <button
            className="google-button"
            type="button"
            disabled={loading !== null}
            onClick={handleGoogle}
          >
            <span aria-hidden="true">G</span>
            {loading === "google" ? "Opening Google…" : "Continue with Google"}
          </button>

          <div className="auth-divider"><span>or continue with email</span></div>

          <form onSubmit={handleEmail}>
            <label>
              Email address
              <input
                required
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </label>
            <button type="submit" disabled={loading !== null}>
              {loading === "email" ? "Sending link…" : "Email me a sign-in link"}
            </button>
          </form>

          {message && <p className="auth-message">{message}</p>}
          <p className="auth-terms">
            By continuing, you agree to process only content you own or can legally use.
          </p>
        </section>
        <Link className="auth-home-link" href="/">Back to ClipCraft</Link>
      </main>
    </div>
  );
}
