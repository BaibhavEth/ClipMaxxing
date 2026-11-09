import type { CaptionStyle, FramingMode, RenderOptions } from "@/lib/types";

export const DEFAULT_RENDER_OPTIONS: RenderOptions = {
  aspect_ratio: "9:16",
  framing: "auto",
  captions: true,
  caption_style: "pop",
  remove_dead_air: true,
  speed: 1,
};

export const CAPTION_OPTIONS: { value: CaptionStyle; label: string; description: string }[] = [
  { value: "pop", label: "Pop", description: "Heavy type, yellow active word" },
  { value: "spotlight", label: "Spotlight", description: "Active word on a violet pill" },
  { value: "impact", label: "Impact", description: "Tall condensed, two words at a time" },
  { value: "boxed", label: "Boxed", description: "Text on a translucent plate" },
  { value: "sweep", label: "Sweep", description: "Karaoke fill as words are spoken" },
  { value: "punch", label: "Punch", description: "One oversized word at a time" },
  { value: "glow", label: "Glow", description: "Soft cyan bloom on the active word" },
  { value: "clean", label: "Clean", description: "Sentence case subtitles" },
  { value: "bold", label: "Bold", description: "Uppercase subtitles" },
  { value: "minimal", label: "Minimal", description: "Small, understated subtitles" },
];

export const FRAMING_OPTIONS: { value: FramingMode; label: string }[] = [
  { value: "auto", label: "Smart (follow faces)" },
  { value: "fill", label: "Always fill the frame" },
  { value: "fit", label: "Fit whole frame" },
];

export const SPEED_OPTIONS = [1, 1.1, 1.25, 1.5].map((speed) => ({
  value: String(speed),
  label: speed === 1 ? "Normal speed" : `${speed}× speed`,
}));

const YOUTUBE_HOSTS = [
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtu.be",
];
const TWITCH_HOSTS = ["twitch.tv", "www.twitch.tv", "m.twitch.tv"];

export function isSupportedVideoUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase().replace(/\.$/, "");
    if (YOUTUBE_HOSTS.includes(host)) return true;
    return TWITCH_HOSTS.includes(host) && /^\/videos\/\d+\/?$/.test(parsed.pathname);
  } catch {
    return false;
  }
}

const LAYOUT_LABELS: Record<string, string> = {
  talking_head: "Speaker tracking",
  two_shot: "Split speakers",
  screen_cam: "Screen + webcam",
  group: "Group fit",
  screen: "Full frame fit",
  original: "Original frame",
};

export function layoutLabel(layout: string): string {
  return LAYOUT_LABELS[layout] ?? layout;
}
