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
export type CaptionStyle = "clean" | "bold" | "minimal";
export type ZoomPreset = "off" | "light" | "medium";
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
}

export interface Clip {
  title: string;
  reason: string;
  start: number;
  end: number;
  filename: string;
  media_url: string;
  download_url: string;
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
}
