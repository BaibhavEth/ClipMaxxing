"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { StudioSelect } from "@/components/studio-select";
import { getClipTranscript, getJob, renderClip } from "@/lib/api";
import type {
  AspectRatio,
  CaptionStyle,
  Clip,
  ClipEditSettings,
  TranscriptWord,
  ZoomPreset,
} from "@/lib/types";

const CAPTION_OPTIONS = [
  { value: "clean", label: "Clean" },
  { value: "bold", label: "Bold" },
  { value: "minimal", label: "Minimal" },
];

const FADE_OPTIONS = [
  { value: "0", label: "None" },
  { value: "0.25", label: "Subtle" },
  { value: "0.5", label: "Medium" },
  { value: "1", label: "Slow" },
];

const ZOOM_OPTIONS = [
  { value: "off", label: "Off" },
  { value: "light", label: "Light" },
  { value: "medium", label: "Medium" },
];

function defaultSettings(clip: Clip, hasWords: boolean): ClipEditSettings {
  return (
    clip.edit_settings ?? {
      trim_start: clip.start,
      trim_end: clip.end,
      aspect_ratio: "original",
      captions: hasWords,
      caption_style: "clean",
      fade_in: 0.25,
      fade_out: 0.25,
      zoom: "off",
    }
  );
}

interface PreviewCaption {
  start: number;
  end: number;
  text: string;
  words: TranscriptWord[];
}

export function buildPreviewCaptions(
  words: TranscriptWord[],
  clipStart: number,
  clipEnd: number,
): PreviewCaption[] {
  const eligible = words.filter(
    (word) => word.end > clipStart && word.start < clipEnd && word.word.trim(),
  );
  const cues: PreviewCaption[] = [];
  let group: TranscriptWord[] = [];

  const flush = () => {
    if (!group.length) return;
    cues.push({
      start: group[0].start,
      end: Math.min(clipEnd, group[group.length - 1].end + 0.08),
      text: group.map((word) => word.word.trim()).join(" "),
      words: [...group],
    });
    group = [];
  };

  for (const word of eligible) {
    const nextText = [...group.map((item) => item.word.trim()), word.word.trim()].join(" ");
    const hasPause = group.length > 0 && word.start - group[group.length - 1].end >= 0.55;
    const tooLong = group.length > 0 && word.end - group[0].start > 3.2;
    if (group.length && (group.length >= 7 || hasPause || tooLong || nextText.length > 40)) {
      flush();
    }
    group.push(word);
    if (/[.!?…]["'’”)]*$/.test(word.word.trim()) && group.length >= 2) {
      flush();
    }
  }
  flush();
  return cues;
}

function captionAt(
  cues: PreviewCaption[],
  absoluteTime: number,
): { cue: PreviewCaption; activeIndex: number } | null {
  const cue = cues.find((item) => item.start <= absoluteTime && item.end >= absoluteTime);
  if (!cue) return null;
  const activeIndex = cue.words.findIndex(
    (word) => word.start <= absoluteTime && word.end + 0.15 >= absoluteTime,
  );
  return { cue, activeIndex: activeIndex < 0 ? 0 : activeIndex };
}

export function ClipEditor({
  jobId,
  filename,
}: {
  jobId: string;
  filename: string;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [clip, setClip] = useState<Clip | null>(null);
  const [words, setWords] = useState<TranscriptWord[]>([]);
  const [settings, setSettings] = useState<ClipEditSettings | null>(null);
  const [caption, setCaption] = useState<{
    cue: PreviewCaption;
    activeIndex: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exported, setExported] = useState(false);
  const [renderStartVersion, setRenderStartVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const previewCaptions = useMemo(
    () =>
      settings
        ? buildPreviewCaptions(words, settings.trim_start, settings.trim_end)
        : [],
    [settings, words],
  );

  useEffect(() => {
    let active = true;
    Promise.all([getJob(jobId), getClipTranscript(jobId, filename)])
      .then(([loadedJob, loadedWords]) => {
        if (!active) return;
        const loadedClip = loadedJob.clips.find((item) => item.filename === filename);
        if (!loadedClip) throw new Error("Clip not found");
        setClip(loadedClip);
        setWords(loadedWords);
        setSettings(defaultSettings(loadedClip, loadedWords.length > 0));
      })
      .catch((loadError) => {
        if (active) {
          setError(loadError instanceof Error ? loadError.message : "Could not load this clip");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [filename, jobId]);

  useEffect(() => {
    if (!exporting) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      try {
        const nextJob = await getJob(jobId);
        if (!active) return;
        const nextClip = nextJob.clips.find((item) => item.filename === filename);
        if (!nextClip) throw new Error("Clip not found");
        setClip(nextClip);
        if (nextClip.render_status === "failed") {
          setError(nextClip.render_error ?? "The edited clip could not be rendered");
          setExporting(false);
          return;
        }
        if (nextClip.render_status === "ready" && nextClip.version > renderStartVersion) {
          setSettings(defaultSettings(nextClip, words.length > 0));
          setExporting(false);
          setExported(true);
          return;
        }
        timer = setTimeout(poll, 1500);
      } catch (pollError) {
        if (!active) return;
        setError(pollError instanceof Error ? pollError.message : "Could not check the render");
        setExporting(false);
      }
    };

    timer = setTimeout(poll, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [exporting, filename, jobId, renderStartVersion, words.length]);

  function updateSetting<K extends keyof ClipEditSettings>(
    key: K,
    value: ClipEditSettings[K],
  ) {
    setExported(false);
    setSettings((current) => (current ? { ...current, [key]: value } : current));
  }

  function restartPreview() {
    if (!clip || !settings || !videoRef.current) return;
    const mediaStart = clip.edit_settings?.trim_start ?? clip.start;
    videoRef.current.currentTime = Math.max(0, settings.trim_start - mediaStart);
    void videoRef.current.play();
  }

  function handleTimeUpdate() {
    if (!clip || !settings || !videoRef.current) return;
    const mediaStart = clip.edit_settings?.trim_start ?? clip.start;
    const absoluteTime = mediaStart + videoRef.current.currentTime;
    setCaption(settings.captions ? captionAt(previewCaptions, absoluteTime) : null);
    if (absoluteTime >= settings.trim_end) {
      videoRef.current.pause();
    }
  }

  async function handleExport() {
    if (!clip || !settings) return;
    setError(null);
    setExported(false);
    setRenderStartVersion(clip.version);
    setExporting(true);
    try {
      await renderClip(jobId, filename, settings);
    } catch (renderError) {
      setError(renderError instanceof Error ? renderError.message : "Could not start the render");
      setExporting(false);
    }
  }

  if (loading) {
    return <div className="editor-loading">Loading editor…</div>;
  }

  if (error && (!clip || !settings)) {
    return (
      <div className="editor-unavailable">
        <h1>Editor unavailable</h1>
        <p>{error}</p>
        <Link href={`/jobs/${jobId}`}>Back to clips</Link>
      </div>
    );
  }

  if (!clip || !settings) return null;

  if (!clip.editable) {
    return (
      <div className="editor-unavailable">
        <h1>This clip can&apos;t be edited</h1>
        <p>Recreate this project to retain the source video required for editing.</p>
        <Link href="/create">Create a new project</Link>
      </div>
    );
  }

  const duration = settings.trim_end - settings.trim_start;
  const zoomScale = { off: 1, light: 1.08, medium: 1.15 }[settings.zoom];

  return (
    <section className="clip-editor">
      <div className="editor-toolbar">
        <div className="editor-toolbar-copy">
          <Link className="back-button" href={`/jobs/${jobId}`}>
            <span aria-hidden="true">←</span>
            Back to clips
          </Link>
          <div className="editor-title-row">
            <div>
              <span className="editor-file-label">{filename}</span>
              <h1>Edit clip</h1>
              <p>{clip.title}</p>
            </div>
            <span className="duration-pill">{duration.toFixed(1)} seconds</span>
          </div>
        </div>
        <div className="editor-toolbar-actions">
          <span className={exported ? "save-state saved" : "save-state"}>
            {exported ? "Export complete" : "Changes not exported"}
          </span>
          <button
            className="export-button"
            type="button"
            disabled={exporting}
            onClick={handleExport}
          >
            {exporting ? "Rendering clip…" : "Export clip"}
          </button>
        </div>
      </div>

      <div className="editor-grid">
        <div className="editor-preview-column">
          <div className="panel-heading">
            <div>
              <h2>Preview</h2>
              <p>Review the crop, captions, and timing before export.</p>
            </div>
            <span>{settings.aspect_ratio === "original" ? "Source format" : settings.aspect_ratio}</span>
          </div>
          <div className={`editor-preview aspect-${settings.aspect_ratio.replace(":", "-")}`}>
            <video
              key={clip.media_url}
              ref={videoRef}
              controls
              preload="metadata"
              src={clip.media_url}
              onTimeUpdate={handleTimeUpdate}
              style={{ transform: `scale(${zoomScale})` }}
            >
              <track kind="captions" />
            </video>
            {caption && (
              <div className={`caption-preview caption-${settings.caption_style}`}>
                {caption.cue.words.map((word, index) => (
                  <span className={index === caption.activeIndex ? "active" : ""} key={index}>
                    {word.word}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="preview-footer">
            <button className="preview-button" type="button" onClick={restartPreview}>
              Play from trim start
            </button>
            <p className="preview-note">
              Final quality is rendered from the original source.
            </p>
          </div>
        </div>

        <div className="editor-controls">
          <div className="panel-heading inspector-heading">
            <div>
              <h2>Adjustments</h2>
              <p>Apply a consistent preset to this clip.</p>
            </div>
          </div>

          <fieldset className="control-section">
            <legend>Trim</legend>
            <div className="trim-values">
              <label>
                Start
                <span>+{(settings.trim_start - clip.start).toFixed(1)}s</span>
              </label>
              <label>
                End
                <span>-{(clip.end - settings.trim_end).toFixed(1)}s</span>
              </label>
            </div>
            <label className="range-control">
              <span className="sr-only">Trim start</span>
              <input
                type="range"
                min={clip.start}
                max={settings.trim_end - 2}
                step="0.1"
                value={settings.trim_start}
                onChange={(event) => updateSetting("trim_start", Number(event.target.value))}
              />
            </label>
            <label className="range-control">
              <span className="sr-only">Trim end</span>
              <input
                type="range"
                min={settings.trim_start + 2}
                max={clip.end}
                step="0.1"
                value={settings.trim_end}
                onChange={(event) => updateSetting("trim_end", Number(event.target.value))}
              />
            </label>
          </fieldset>

          <fieldset className="control-section">
            <legend>Format</legend>
            <div className="choice-row">
              {(["original", "9:16", "1:1"] as AspectRatio[]).map((aspect) => (
                <button
                  className={settings.aspect_ratio === aspect ? "selected" : ""}
                  key={aspect}
                  type="button"
                  onClick={() => updateSetting("aspect_ratio", aspect)}
                >
                  {aspect === "original" ? "Original" : aspect}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset className="control-section">
            <legend>Captions</legend>
            <label className="toggle-row">
              <span>
                Burn in captions
                <small>{words.length ? "Generated from the transcript" : "Unavailable"}</small>
              </span>
              <input
                type="checkbox"
                checked={settings.captions}
                disabled={!words.length}
                onChange={(event) => updateSetting("captions", event.target.checked)}
              />
            </label>
            {settings.captions && (
              <StudioSelect
                label="Caption style"
                value={settings.caption_style}
                options={CAPTION_OPTIONS}
                onChange={(value) => updateSetting("caption_style", value as CaptionStyle)}
              />
            )}
          </fieldset>

          <fieldset className="control-section">
            <legend>Effects</legend>
            <div className="effect-selects">
              <StudioSelect
                label="Fade"
                value={String(settings.fade_in)}
                options={FADE_OPTIONS}
                onChange={(value) => {
                  const fade = Number(value);
                  setExported(false);
                  setSettings((current) =>
                    current ? { ...current, fade_in: fade, fade_out: fade } : current,
                  );
                }}
              />
              <StudioSelect
                label="Punch zoom"
                value={settings.zoom}
                options={ZOOM_OPTIONS}
                onChange={(value) => updateSetting("zoom", value as ZoomPreset)}
              />
            </div>
          </fieldset>

          {error && <div className="editor-error">{error}</div>}
        </div>
      </div>
    </section>
  );
}
