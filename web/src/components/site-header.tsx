"use client";

import Link from "next/link";

import { AccountNav } from "@/components/account-nav";

interface SiteHeaderProps {
  action?: boolean;
  account?: boolean;
  signIn?: boolean;
  context?: string;
  actionLabel?: string;
  actionHref?: string;
}

export function SiteHeader({
  action = false,
  account = false,
  signIn = false,
  context,
  actionLabel,
  actionHref = "/create",
}: SiteHeaderProps) {
  const showAction = action || Boolean(actionLabel);
  const showAccount = account || Boolean(context);

  return (
    <header className={`site-header${context ? " app-header" : ""}`}>
      <div className="header-identity">
        <Link className="site-brand" href="/">
          <span className="site-brand-mark" aria-hidden="true">
            <i />
          </span>
          ClipCraft
        </Link>
        {context && <span className="header-context">{context}</span>}
      </div>
      <div className="header-actions">
        {showAction && (
          <Link className="header-action" href={actionHref}>
            {actionLabel ?? "Start clipping"}
          </Link>
        )}
        {signIn && (
          <nav className="account-nav" aria-label="Account navigation">
            <Link href="/login">Sign in</Link>
          </nav>
        )}
        {showAccount && <AccountNav />}
      </div>
    </header>
  );
}
