"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { CaptionStylePicker } from "@/components/caption-style-picker";
import { SiteHeader } from "@/components/site-header";
import { StudioSelect } from "@/components/studio-select";
import { createJob, uploadJob } from "@/lib/api";
import {
  DEFAULT_RENDER_OPTIONS,
  FRAMING_OPTIONS,
  isSupportedVideoUrl,
  SPEED_OPTIONS,
} from "@/lib/render-options";
import type { AspectRatio, FramingMode, RenderOptions } from "@/lib/types";

const CLIP_COUNT_OPTIONS = [3, 4, 5, 6, 7, 8].map((count) => ({
  value: String(count),
  label: `${count} clips`,
}));

const DURATION_OPTIONS = [30, 45, 60, 90].map((seconds) => ({
  value: String(seconds),
  label: `Around ${seconds} seconds`,
}));

const FORMAT_OPTIONS: { value: AspectRatio; label: string }[] = [
  { value: "9:16", label: "Vertical 9:16" },
  { value: "1:1", label: "Square 1:1" },
  { value: "original", label: "Original" },
];

type SourceMode = "link" | "upload";

export default function CreatePage() {
  const router = useRouter();
  const [mode, setMode] = useState<SourceMode>("link");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [clipCount, setClipCount] = useState(5);
  const [duration, setDuration] = useState(45);
  const [render, setRender] = useState<RenderOptions>(DEFAULT_RENDER_OPTIONS);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  function updateRender<K extends keyof RenderOptions>(key: K, value: RenderOptions[K]) {
    setRender((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    try {
      let jobId: string;
      if (mode === "link") {
        if (!isSupportedVideoUrl(url)) throw new Error("Paste a valid YouTube or Twitch VOD URL");
        setSubmitting(true);
        jobId = await createJob({
          url,
          clip_count: clipCount,
          target_duration: duration,
          render,
        });
      } else {
        if (!file) throw new Error("Choose a video file to upload");
        setSubmitting(true);
        setUploadProgress(0);
        jobId = await uploadJob(
          { file, clip_count: clipCount, target_duration: duration, render },
          setUploadProgress,
        );
      }
      router.push(`/jobs/${jobId}`);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Could not start the job");
      setSubmitting(false);
      setUploadProgress(null);
    }
  }

  const submitLabel =
    uploadProgress !== null
      ? `Uploading ${Math.round(uploadProgress * 100)}%`
      : submitting
        ? "Starting project…"
        : "Continue";

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
          <p>Paste a public YouTube or Twitch video, or upload your own recording.</p>
        </div>

        <form className="create-form" onSubmit={handleSubmit}>
          <div className="source-tabs" role="tablist" aria-label="Video source">
            {(
              [
                ["link", "Paste a link"],
                ["upload", "Upload a file"],
              ] as [SourceMode, string][]
            ).map(([value, label]) => (
              <button
                aria-selected={mode === value}
                key={value}
                role="tab"
                type="button"
                disabled={submitting}
                onClick={() => {
                  setMode(value);
                  setError(null);
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {mode === "link" ? (
            <label className="create-url-field">
              <span>YouTube or Twitch URL</span>
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
          ) : (
            <label className={file ? "upload-drop has-file" : "upload-drop"}>
              <span className="upload-drop-label">Video file</span>
              <strong>{file ? file.name : "Choose a video"}</strong>
              <small>
                {file
                  ? `${(file.size / 1024 / 1024).toFixed(1)} MB`
                  : "MP4, MOV, M4V, MKV, WebM, or AVI"}
              </small>
              <input
                aria-label="Video file"
                type="file"
                accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo,.mp4,.mov,.m4v,.mkv,.webm,.avi"
                disabled={submitting}
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              {uploadProgress !== null && (
                <span className="upload-progress">
                  <span style={{ width: `${Math.round(uploadProgress * 100)}%` }} />
                </span>
              )}
            </label>
          )}

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

          <div className="create-section">
            <span className="create-section-label">Format</span>
            <div className="choice-row">
              {FORMAT_OPTIONS.map((option) => (
                <button
                  className={render.aspect_ratio === option.value ? "selected" : ""}
                  disabled={submitting}
                  key={option.value}
                  type="button"
                  onClick={() => updateRender("aspect_ratio", option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          <div className="create-section">
            <label className="toggle-row">
              <span>
                Captions
                <small>Word-by-word, synced to the transcript</small>
              </span>
              <input
                type="checkbox"
                checked={render.captions}
                disabled={submitting}
                onChange={(event) => updateRender("captions", event.target.checked)}
              />
            </label>
            {render.captions && (
              <CaptionStylePicker
                value={render.caption_style}
                disabled={submitting}
                onChange={(value) => updateRender("caption_style", value)}
              />
            )}
          </div>

          <div className="create-options">
            <StudioSelect
              label="Framing"
              value={render.framing}
              options={FRAMING_OPTIONS}
              disabled={submitting || render.aspect_ratio === "original"}
              onChange={(value) => updateRender("framing", value as FramingMode)}
            />
            <StudioSelect
              label="Speed"
              value={String(render.speed)}
              options={SPEED_OPTIONS}
              disabled={submitting}
              onChange={(value) => updateRender("speed", Number(value))}
            />
          </div>

          <div className="create-section">
            <label className="toggle-row">
              <span>
                Remove dead air
                <small>Cuts long pauses and “um”s, keeping a natural breath</small>
              </span>
              <input
                type="checkbox"
                checked={render.remove_dead_air}
                disabled={submitting}
                onChange={(event) => updateRender("remove_dead_air", event.target.checked)}
              />
            </label>
          </div>

          <div className="create-submit-row">
            <p>
              Clips are reviewed for complete thoughts, then framed to follow whoever is
              speaking. You can fine-tune every clip afterwards.
            </p>
            <button type="submit" disabled={submitting}>
              {submitLabel}
            </button>
          </div>
        </form>

        {error && <div className="create-error">{error}</div>}
      </main>
    </div>
  );
}
