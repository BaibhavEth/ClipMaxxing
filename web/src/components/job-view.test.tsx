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
    const quotePost = "A surprising business lesson…\n\n“An exact quote from the clip.”";
    const storyPost =
      "Brian Armstrong built Coinbase from 8pm to midnight\n\nhe never touched Airbnb's laptop doing it\n\nfriendships were the actual cost";
    const breakdownPost =
      "Brian Armstrong built Coinbase while working at Airbnb\n\n8pm to midnight, 3 to 4 nights a week\n\nWould you trade 18 months of weekends for that?";
    mockedGeneratePost.mockResolvedValue({
      text: quotePost,
      story_text: storyPost,
      breakdown_text: breakdownPost,
    });
    render(<JobView jobId="job-id" />);

    fireEvent.click(await screen.findByRole("button", { name: "Generate X posts" }));

    expect(await screen.findByRole("textbox", { name: "Story X post draft" })).toHaveValue(
      storyPost,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Breakdown" }));
    expect(screen.getByRole("textbox", { name: "Breakdown X post draft" })).toHaveValue(
      breakdownPost,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Quote" }));
    expect(screen.getByRole("textbox", { name: "Quote X post draft" })).toHaveValue(quotePost);
    fireEvent.click(screen.getByRole("button", { name: "Copy post" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(quotePost);
  });
});
