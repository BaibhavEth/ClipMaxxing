export type JobStatus =
  | "queued"
  | "downloading"
  | "transcribing"
  | "analyzing"
  | "rendering"
  | "complete"
  | "failed";

export interface VideoInfo {
  title: string;
  duration: number;
  source_url: string;
  thumbnail_url: string | null;
}

export type AspectRatio = "original" | "9:16" | "1:1";
export type CaptionStyle =
  | "clean"
  | "bold"
  | "minimal"
  | "pop"
  | "spotlight"
  | "impact"
  | "boxed"
  | "sweep"
  | "punch"
  | "glow";
export type ZoomPreset = "off" | "light" | "medium";
export type FramingMode = "auto" | "fill" | "fit";
export type SourceKind = "youtube" | "twitch" | "upload";
export type ClipRenderStatus = "ready" | "rendering" | "failed";

export interface TranscriptWord {
  start: number;
  end: number;
  word: string;
}

export interface ClipEditSettings {
  trim_start: number;
  trim_end: number;
  aspect_ratio: AspectRatio;
  captions: boolean;
  caption_style: CaptionStyle;
  fade_in: number;
  fade_out: number;
  zoom: ZoomPreset;
  framing: FramingMode;
  remove_dead_air: boolean;
  speed: number;
}

export interface RenderOptions {
  aspect_ratio: AspectRatio;
  framing: FramingMode;
  captions: boolean;
  caption_style: CaptionStyle;
  remove_dead_air: boolean;
  speed: number;
}

export interface RenderReport {
  output_duration: number;
  removed_seconds: number;
  layouts: string[];
}

export interface Clip {
  title: string;
  reason: string;
  start: number;
  end: number;
  score?: number | null;
  filename: string;
  media_url: string;
  download_url: string;
  preview_url?: string;
  preview_start?: number | null;
  render_report?: RenderReport | null;
  editable: boolean;
  edit_settings: ClipEditSettings | null;
  render_status: ClipRenderStatus;
  render_error: string | null;
  version: number;
  social_post: string | null;
}

export interface Job {
  id: string;
  status: JobStatus;
  progress: number;
  message: string;
  video: VideoInfo | null;
  clips: Clip[];
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateJobInput {
  url: string;
  clip_count: number;
  target_duration: number;
  render?: RenderOptions;
}

export interface UploadJobInput {
  file: File;
  clip_count: number;
  target_duration: number;
  render: RenderOptions;
}

export interface ProjectSummary {
  id: string;
  source_url: string;
  source_kind?: SourceKind;
  title: string | null;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
  clip_count: number;
  target_duration: number;
  created_at: string;
  updated_at: string;
}
