"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { generateSocialPost, getJob } from "@/lib/api";
import { layoutLabel } from "@/lib/render-options";
import {
  parseSocialPosts,
  SOCIAL_STYLES,
  type SocialPosts,
  type SocialStyle,
} from "@/lib/social-posts";
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
  const [posts, setPosts] = useState<SocialPosts>(() => parseSocialPosts(clip.social_post));
  const [activeStyle, setActiveStyle] = useState<SocialStyle>("quote");
  const [showSocialPost, setShowSocialPost] = useState(false);
  const [generatingPost, setGeneratingPost] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const activePost = posts[activeStyle];
  const hasAllPosts = Boolean(posts.quote && posts.story && posts.breakdown);
  const activeLabel = SOCIAL_STYLES.find(({ style }) => style === activeStyle)?.label;
  const aspect = clip.edit_settings?.aspect_ratio ?? "original";
  const report = clip.render_report;
  const shownDuration = report?.output_duration || shownEnd - shownStart;
  const details = [
    aspect === "original" ? "Original format" : aspect,
    report?.layouts[0] ? layoutLabel(report.layouts[0]) : null,
    report && report.removed_seconds >= 0.1
      ? `${report.removed_seconds.toFixed(1)}s dead air cut`
      : null,
  ].filter(Boolean);

  async function handleGeneratePost() {
    if (hasAllPosts) {
      setShowSocialPost(true);
      return;
    }
    setGeneratingPost(true);
    setPostError(null);
    try {
      const generated = await generateSocialPost(jobId, clip.filename);
      setPosts({
        quote: generated.text,
        story: generated.story_text,
        breakdown: generated.breakdown_text,
      });
      setActiveStyle(generated.story_text ? "story" : "quote");
      setShowSocialPost(true);
    } catch (error) {
      setPostError(error instanceof Error ? error.message : "Could not generate the post");
    } finally {
      setGeneratingPost(false);
    }
  }

  async function handleCopyPost() {
    try {
      await navigator.clipboard.writeText(activePost);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setPostError("Copy failed. Select the text and copy it manually.");
    }
  }

  return (
    <article className="result-card">
      <div className={`result-video aspect-${aspect.replace(":", "-")}`}>
        <video controls preload="metadata" src={clip.media_url}>
          <track kind="captions" />
        </video>
        <div className="result-video-meta">
          <span>Clip {String(index + 1).padStart(2, "0")}</span>
          <span>{Math.round(shownDuration)} sec</span>
        </div>
        {clip.score != null && (
          <span className="result-score" title="Editor score out of 10">
            {clip.score.toFixed(1)}
          </span>
        )}
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
          <span>{details.join(" · ")}</span>
        </div>
        <button
          className="social-post-trigger"
          type="button"
          disabled={generatingPost}
          onClick={handleGeneratePost}
        >
          {generatingPost
            ? "Writing X posts…"
            : hasAllPosts
              ? "View X posts"
              : "Generate X posts"}
        </button>
        {postError && <p className="result-render-error">{postError}</p>}
        {showSocialPost && (
          <div className="social-composer">
            <div className="social-composer-heading">
              <div>
                <span>X post drafts</span>
                <p>Quote, three-beat story, and in-depth breakdown</p>
              </div>
              <button type="button" onClick={() => setShowSocialPost(false)}>
                Close
              </button>
            </div>
            <div className="social-style-tabs" role="tablist" aria-label="X post format">
              {SOCIAL_STYLES.map(({ style, label }) => (
                <button
                  aria-selected={activeStyle === style}
                  key={style}
                  role="tab"
                  type="button"
                  onClick={() => {
                    setActiveStyle(style);
                    setCopied(false);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <textarea
              aria-label={`${activeLabel} X post draft`}
              className={activeStyle === "breakdown" ? "social-breakdown" : undefined}
              value={activePost}
              onChange={(event) => {
                setPosts((current) => ({ ...current, [activeStyle]: event.target.value }));
                setCopied(false);
              }}
            />
            <div className="social-composer-footer">
              <span>
                {activePost.length} characters
                {activePost.length > 280 && " · needs X Premium"}
              </span>
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
        <p>{job.error ?? "Try another public video or upload a file."}</p>
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
