import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobView } from "@/components/job-view";
import { generateSocialPost, getJob } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  generateSocialPost: vi.fn(),
  getJob: vi.fn(),
}));

const mockedGetJob = vi.mocked(getJob);
const mockedGeneratePost = vi.mocked(generateSocialPost);

describe("job view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("shows clip results when processing completes", async () => {
    mockedGetJob.mockResolvedValue({
      id: "job-id",
      status: "complete",
      progress: 100,
      message: "Created 1 clip",
      video: {
        title: "A long interview",
        duration: 3600,
        source_url: "https://youtu.be/example",
        thumbnail_url: null,
      },
      clips: [
        {
          title: "The key idea",
          reason: "It is useful on its own",
          start: 10,
          end: 55,
          filename: "clip-01.mp4",
          media_url: "http://localhost:8000/media.mp4",
          download_url: "http://localhost:8000/media.mp4?download=true",
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
    });

    render(<JobView jobId="job-id" />);

    expect(await screen.findByText("The key idea")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download clip" })).toHaveAttribute(
      "href",
      "http://localhost:8000/media.mp4?download=true",
    );
    expect(screen.getByRole("link", { name: "New project" })).toHaveAttribute(
      "href",
      "/create",
    );
    expect(screen.getByRole("link", { name: "Edit clip" })).toHaveAttribute(
      "href",
      "/jobs/job-id/clips/clip-01.mp4/edit",
    );
  });

  it("generates editable X post copy for a clip", async () => {
    mockedGetJob.mockResolvedValue({
      id: "job-id",
      status: "complete",
      progress: 100,
      message: "Created 1 clip",
      video: {
        title: "A long interview",
        duration: 3600,
        source_url: "https://youtu.be/example",
        thumbnail_url: null,
      },
      clips: [
        {
          title: "The key idea",
          reason: "It is useful on its own",
          start: 10,
          end: 55,
          filename: "clip-01.mp4",
          media_url: "http://localhost:8000/media.mp4",
          download_url: "http://localhost:8000/media.mp4?download=true",
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
    });
    const post = "A surprising business lesson…\n\n“An exact quote from the clip.”";
    mockedGeneratePost.mockResolvedValue(post);
    render(<JobView jobId="job-id" />);

    fireEvent.click(await screen.findByRole("button", { name: "Generate X post" }));

    expect(await screen.findByRole("textbox", { name: "X post draft" })).toHaveValue(post);
    fireEvent.click(screen.getByRole("button", { name: "Copy post" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(post);
  });
});
