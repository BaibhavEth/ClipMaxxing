"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { SiteHeader } from "@/components/site-header";
import { StudioSelect } from "@/components/studio-select";
import { createJob } from "@/lib/api";

const CLIP_COUNT_OPTIONS = [3, 4, 5, 6, 7, 8].map((count) => ({
  value: String(count),
  label: `${count} clips`,
}));

const DURATION_OPTIONS = [30, 45, 60, 90].map((seconds) => ({
  value: String(seconds),
  label: `Around ${seconds} seconds`,
}));

export default function CreatePage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [clipCount, setClipCount] = useState(5);
  const [duration, setDuration] = useState(45);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    try {
      const parsed = new URL(url);
      const host = parsed.hostname.toLowerCase().replace(/\.$/, "");
      const allowed = [
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
      ];
      if (!allowed.includes(host)) throw new Error("Paste a valid YouTube URL");

      setSubmitting(true);
      const jobId = await createJob({
        url,
        clip_count: clipCount,
        target_duration: duration,
      });
      router.push(`/jobs/${jobId}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not start the job");
      setSubmitting(false);
    }
  }

  return (
    <div className="create-page">
      <SiteHeader context="Create" />

      <main className="create-main">
        <Link className="back-link" href="/">
          <span aria-hidden="true">←</span>
          Back to home
        </Link>
        <div className="create-heading">
          <h1>Create clips</h1>
          <p>Paste a public YouTube video and choose how many clips you want.</p>
        </div>

        <form className="create-form" onSubmit={handleSubmit}>
          <label className="create-url-field">
            <span>YouTube URL</span>
            <input
              required
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              disabled={submitting}
              autoFocus
            />
          </label>

          <div className="create-options">
            <StudioSelect
              label="Number of clips"
              value={String(clipCount)}
              options={CLIP_COUNT_OPTIONS}
              disabled={submitting}
              onChange={(value) => setClipCount(Number(value))}
            />
            <StudioSelect
              label="Target length"
              value={String(duration)}
              options={DURATION_OPTIONS}
              disabled={submitting}
              onChange={(value) => setDuration(Number(value))}
            />
          </div>

          <div className="create-submit-row">
            <p>Clip boundaries may extend slightly so complete thoughts stay intact.</p>
            <button type="submit" disabled={submitting}>
              {submitting ? "Starting project…" : "Continue"}
            </button>
          </div>
        </form>

        {error && <div className="create-error">{error}</div>}
      </main>
    </div>
  );
}
