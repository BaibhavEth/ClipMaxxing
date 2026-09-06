import Link from "next/link";

interface SiteHeaderProps {
  action?: boolean;
  context?: string;
  actionLabel?: string;
  actionHref?: string;
}

export function SiteHeader({
  action = false,
  context,
  actionLabel,
  actionHref = "/create",
}: SiteHeaderProps) {
  const showAction = action || Boolean(actionLabel);

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
      {showAction && (
        <Link className="header-action" href={actionHref}>
          {actionLabel ?? "Start clipping"}
        </Link>
      )}
    </header>
  );
}
