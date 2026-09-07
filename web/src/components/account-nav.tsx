"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";

export function AccountNav() {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return <nav className="account-nav" aria-label="Account navigation" />;
  }

  return <SignedInNav />;
}

function SignedInNav() {
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const supabase = createClient();
    void supabase.auth
      .getUser()
      .then(({ data }: { data: { user: { email?: string } | null } }) => {
        setEmail(data.user?.email ?? null);
      })
      .finally(() => setReady(true));
  }, []);

  async function signOut() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  if (!ready) {
    return <nav className="account-nav" aria-label="Account navigation" />;
  }

  if (!email) {
    return (
      <nav className="account-nav" aria-label="Account navigation">
        <Link href="/login">Sign in</Link>
      </nav>
    );
  }

  return (
    <nav className="account-nav" aria-label="Account navigation">
      <Link href="/history">History</Link>
      <Link href="/settings">Settings</Link>
      <span title={email}>{email}</span>
      <button type="button" onClick={signOut}>
        Sign out
      </button>
    </nav>
  );
}
