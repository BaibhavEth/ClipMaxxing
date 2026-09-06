import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { buildPreviewCaptions, ClipEditor } from "@/components/clip-editor";
import { getClipTranscript, getJob, renderClip } from "@/lib/api";
import type { Job } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  getClipTranscript: vi.fn(),
  getJob: vi.fn(),
  renderClip: vi.fn(),
}));

const mockedGetJob = vi.mocked(getJob);
const mockedGetTranscript = vi.mocked(getClipTranscript);
const mockedRenderClip = vi.mocked(renderClip);

const job: Job = {
  id: "job-id",
  status: "complete",
  progress: 100,
  message: "Done",
  video: {
    title: "A long interview",
    duration: 3600,
    source_url: "https://youtu.be/example",
    thumbnail_url: null,
  },
  clips: [
    {
      title: "The key idea",
      reason: "It stands alone",
      start: 10,
      end: 55,
      filename: "clip-01.mp4",
      media_url: "http://localhost:8000/clip-01.mp4?v=0",
      download_url: "http://localhost:8000/clip-01.mp4?download=true&v=0",
      editable: true,
      edit_settings: null,
      render_status: "ready",
      render_error: null,
      version: 0,
      social_post: null,
    },
  ],
  error: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:01:00Z",
};

describe("clip editor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetJob.mockResolvedValue(job);
    mockedGetTranscript.mockResolvedValue([
      { start: 10, end: 10.4, word: "A" },
      { start: 10.5, end: 11, word: "thought" },
    ]);
    mockedRenderClip.mockResolvedValue();
  });

  it("submits selected trim and format settings", async () => {
    render(<ClipEditor jobId="job-id" filename="clip-01.mp4" />);

    expect(await screen.findByRole("heading", { name: "Edit clip" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider", { name: "Trim start" }), {
      target: { value: "12" },
    });
    fireEvent.click(screen.getByRole("button", { name: "9:16" }));
    fireEvent.click(screen.getByRole("button", { name: "Export clip" }));

    await waitFor(() =>
      expect(mockedRenderClip).toHaveBeenCalledWith(
        "job-id",
        "clip-01.mp4",
        expect.objectContaining({
          trim_start: 12,
          trim_end: 55,
          aspect_ratio: "9:16",
          captions: true,
        }),
      ),
    );
  });

  it("explains why a legacy clip cannot be edited", async () => {
    mockedGetJob.mockResolvedValue({
      ...job,
      clips: [{ ...job.clips[0], editable: false }],
    });
    mockedGetTranscript.mockResolvedValue([]);

    render(<ClipEditor jobId="job-id" filename="clip-01.mp4" />);

    expect(await screen.findByText("This clip can't be edited")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a new project" })).toHaveAttribute(
      "href",
      "/create",
    );
  });

  it("keeps preview captions stable at sentence and pause boundaries", () => {
    const captions = buildPreviewCaptions(
      [
        { start: 0, end: 0.3, word: "This" },
        { start: 0.35, end: 0.7, word: "works." },
        { start: 1.5, end: 1.8, word: "New" },
        { start: 1.85, end: 2.2, word: "thought" },
      ],
      0,
      3,
    );

    expect(captions.map((cue) => cue.text)).toEqual(["This works.", "New thought"]);
  });
});
