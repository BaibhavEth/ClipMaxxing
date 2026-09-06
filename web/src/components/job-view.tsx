"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { generateSocialPost, getJob } from "@/lib/api";
import type { Clip, Job, JobStatus } from "@/lib/types";

const STEPS: { status: JobStatus; label: string }[] = [
  { status: "downloading", label: "Importing video" },
  { status: "transcribing", label: "Reading transcript" },
  { status: "analyzing", label: "Finding moments" },
  { status: "rendering", label: "Rendering clips" },
];

const STATUS_ORDER: Record<JobStatus, number> = {
  queued: 0,
  downloading: 0,
  transcribing: 1,
  analyzing: 2,
  rendering: 3,
  complete: 4,
  failed: -1,
};

function formatTime(seconds: number): string {
  const rounded = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  const remaining = rounded % 60;
  return hours
    ? `${hours}:${minutes.toString().padStart(2, "0")}:${remaining
        .toString()
        .padStart(2, "0")}`
    : `${minutes}:${remaining.toString().padStart(2, "0")}`;
}

function ClipCard({
  clip,
  index,
  jobId,
}: {
  clip: Clip;
  index: number;
  jobId: string;
}) {
  const shownStart = clip.edit_settings?.trim_start ?? clip.start;
  const shownEnd = clip.edit_settings?.trim_end ?? clip.end;
  const [socialPost, setSocialPost] = useState(clip.social_post ?? "");
  const [showSocialPost, setShowSocialPost] = useState(false);
  const [generatingPost, setGeneratingPost] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleGeneratePost() {
    if (socialPost) {
      setShowSocialPost(true);
      return;
    }
    setGeneratingPost(true);
    setPostError(null);
    try {
      const text = await generateSocialPost(jobId, clip.filename);
      setSocialPost(text);
      setShowSocialPost(true);
    } catch (error) {
      setPostError(error instanceof Error ? error.message : "Could not generate the post");
    } finally {
      setGeneratingPost(false);
    }
  }

  async function handleCopyPost() {
    try {
      await navigator.clipboard.writeText(socialPost);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setPostError("Copy failed. Select the text and copy it manually.");
    }
  }

  return (
    <article className="result-card">
      <div className="result-video">
        <video controls preload="metadata" src={clip.media_url}>
          <track kind="captions" />
        </video>
        <div className="result-video-meta">
          <span>Clip {String(index + 1).padStart(2, "0")}</span>
          <span>{Math.round(shownEnd - shownStart)} sec</span>
        </div>
      </div>
      <div className="result-card-body">
        <span className="result-time">
          {formatTime(shownStart)} — {formatTime(shownEnd)}
        </span>
        <h2>{clip.title}</h2>
        <p>{clip.reason}</p>
        <div className="result-card-footer">
          <div>
            <a href={clip.download_url}>Download clip</a>
            {clip.render_status === "rendering" && (
              <span className="rendering-action">Rendering…</span>
            )}
            {clip.editable && clip.render_status !== "rendering" && (
              <Link href={`/jobs/${jobId}/clips/${encodeURIComponent(clip.filename)}/edit`}>
                Edit clip
              </Link>
            )}
          </div>
          <span>MP4 · Original quality</span>
        </div>
        <button
          className="social-post-trigger"
          type="button"
          disabled={generatingPost}
          onClick={handleGeneratePost}
        >
          {generatingPost
            ? "Writing X post…"
            : socialPost
              ? "View X post"
              : "Generate X post"}
        </button>
        {postError && <p className="result-render-error">{postError}</p>}
        {showSocialPost && (
          <div className="social-composer">
            <div className="social-composer-heading">
              <div>
                <span>X post draft</span>
                <p>Iced Coffee Hour format</p>
              </div>
              <button type="button" onClick={() => setShowSocialPost(false)}>
                Close
              </button>
            </div>
            <textarea
              aria-label="X post draft"
              value={socialPost}
              onChange={(event) => {
                setSocialPost(event.target.value);
                setCopied(false);
              }}
            />
            <div className="social-composer-footer">
              <span>{socialPost.length} characters</span>
              <button type="button" onClick={handleCopyPost}>
                {copied ? "Copied" : "Copy post"}
              </button>
            </div>
          </div>
        )}
        {clip.render_status === "failed" && clip.render_error && (
          <p className="result-render-error">{clip.render_error}</p>
        )}
      </div>
    </article>
  );
}

function LoadingView({ job }: { job: Job | null }) {
  const currentStep = job ? STATUS_ORDER[job.status] : 0;
  const progress = job?.progress ?? 0;

  return (
    <div className="job-loading">
      <div className="job-loading-heading">
        <div>
          <span>Project in progress</span>
          <h1>{job?.video?.title ?? "Creating your clips"}</h1>
          <p>{job?.message ?? "Connecting to the processing service"}</p>
        </div>
        <strong>{progress}%</strong>
      </div>

      <div className="job-progress-track">
        <span style={{ width: `${progress}%` }} />
      </div>

      <div className="job-steps">
        {STEPS.map((step, index) => (
          <div
            className={`job-step${index === currentStep ? " active" : ""}${
              index < currentStep ? " done" : ""
            }`}
            key={step.status}
          >
            <i>{index < currentStep ? "✓" : index + 1}</i>
            <span>{step.label}</span>
          </div>
        ))}
      </div>

      <div className="loading-cards" aria-hidden="true">
        {[0, 1].map((index) => (
          <div className="loading-card" key={index}>
            <div className="loading-video" />
            <div className="loading-lines">
              <span />
              <span />
              <span />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function JobView({ jobId }: { jobId: string }) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const nextJob = await getJob(jobId);
        if (!active) return;
        setJob(nextJob);
        setError(null);
        const clipIsRendering = nextJob.clips.some(
          (clip) => clip.render_status === "rendering",
        );
        if (
          (nextJob.status !== "complete" && nextJob.status !== "failed") ||
          clipIsRendering
        ) {
          timer = setTimeout(poll, 1500);
        }
      } catch (pollError) {
        if (!active) return;
        setError(pollError instanceof Error ? pollError.message : "Could not load this project");
        timer = setTimeout(poll, 3000);
      }
    };

    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [jobId]);

  if (job?.status === "failed") {
    return (
      <section className="job-failed">
        <span>Processing stopped</span>
        <h1>We couldn&apos;t finish this video.</h1>
        <p>{job.error ?? "Try another public YouTube video."}</p>
        <Link href="/create">Start a new project</Link>
      </section>
    );
  }

  if (job?.status === "complete") {
    const sourceDuration = job.video ? formatTime(job.video.duration) : "";
    return (
      <section className="job-results">
        <div className="job-results-heading">
          <div>
            <span>Project complete</span>
            <h1>{job.video?.title}</h1>
            <p>
              {job.clips.length} clips from a {sourceDuration} source
            </p>
          </div>
          <Link href="/create">New project</Link>
        </div>
        <div className="results-grid">
          {job.clips.map((clip, index) => (
            <ClipCard clip={clip} index={index} jobId={jobId} key={clip.filename} />
          ))}
        </div>
      </section>
    );
  }

  return (
    <>
      {error && <div className="job-load-error">{error}. Retrying…</div>}
      <LoadingView job={job} />
    </>
  );
}
