"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SiteHeader } from "@/components/site-header";
import { getProjects } from "@/lib/api";
import type { ProjectSummary } from "@/lib/types";

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export default function HistoryPage() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getProjects()
      .then(setProjects)
      .catch((loadError) =>
        setError(loadError instanceof Error ? loadError.message : "Could not load projects"),
      )
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="account-page">
      <SiteHeader context="History" actionLabel="New project" />
      <main className="account-main">
        <div className="account-page-heading">
          <div>
            <h1>Project history</h1>
            <p>Track every video you have processed with this account.</p>
          </div>
        </div>

        {loading && <div className="account-empty">Loading projects…</div>}
        {error && <div className="account-error">{error}</div>}
        {!loading && !error && projects.length === 0 && (
          <div className="account-empty">
            <h2>No projects yet</h2>
            <p>Create your first project to start building clip history.</p>
            <Link href="/create">Create a project</Link>
          </div>
        )}
        {projects.length > 0 && (
          <div className="history-list">
            {projects.map((project) => (
              <article className="history-row" key={project.id}>
                <div className="history-status">
                  <span className={`status-dot status-${project.status}`} />
                  {project.status}
                </div>
                <div className="history-copy">
                  <h2>{project.title ?? "Processing video"}</h2>
                  <p>{formatDate(project.created_at)}</p>
                </div>
                <div className="history-meta">
                  <span>{project.clip_count} clips</span>
                  <span>{project.progress}%</span>
                </div>
                <Link href={`/jobs/${project.id}`}>Open project</Link>
              </article>
            ))}
          </div>
        )}
        <p className="history-retention">
          Project metadata remains in your history. Local media is currently retained for 24 hours.
        </p>
      </main>
    </div>
  );
}
