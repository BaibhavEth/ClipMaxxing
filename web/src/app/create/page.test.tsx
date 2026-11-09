import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CreatePage from "@/app/create/page";
import { createJob, uploadJob } from "@/lib/api";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  createJob: vi.fn(),
  uploadJob: vi.fn(),
}));

const mockedCreateJob = vi.mocked(createJob);
const mockedUploadJob = vi.mocked(uploadJob);

describe("create page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a job with the chosen style and moves to its page", async () => {
    mockedCreateJob.mockResolvedValue("job-id");
    render(<CreatePage />);

    fireEvent.change(screen.getByPlaceholderText("https://www.youtube.com/watch?v=..."), {
      target: { value: "https://youtu.be/example" },
    });
    fireEvent.click(screen.getByRole("radio", { name: /Impact/ }));
    fireEvent.click(screen.getByRole("button", { name: "Square 1:1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Remove dead air/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(mockedCreateJob).toHaveBeenCalledWith({
        url: "https://youtu.be/example",
        clip_count: 5,
        target_duration: 45,
        render: expect.objectContaining({
          aspect_ratio: "1:1",
          caption_style: "impact",
          remove_dead_air: false,
          framing: "auto",
        }),
      }),
    );
    expect(push).toHaveBeenCalledWith("/jobs/job-id");
  });

  it("accepts Twitch VOD links", async () => {
    mockedCreateJob.mockResolvedValue("job-id");
    render(<CreatePage />);

    fireEvent.change(screen.getByPlaceholderText("https://www.youtube.com/watch?v=..."), {
      target: { value: "https://www.twitch.tv/videos/123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(mockedCreateJob).toHaveBeenCalled());
  });

  it("rejects an unsupported URL before submitting", async () => {
    render(<CreatePage />);

    fireEvent.change(screen.getByPlaceholderText("https://www.youtube.com/watch?v=..."), {
      target: { value: "https://example.com/video" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Paste a valid YouTube or Twitch VOD URL")).toBeInTheDocument();
    expect(mockedCreateJob).not.toHaveBeenCalled();
  });

  it("uploads a local file", async () => {
    mockedUploadJob.mockResolvedValue("upload-id");
    render(<CreatePage />);

    fireEvent.click(screen.getByRole("tab", { name: "Upload a file" }));
    const file = new File(["video"], "talk.mp4", { type: "video/mp4" });
    fireEvent.change(screen.getByLabelText("Video file"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(mockedUploadJob).toHaveBeenCalledWith(
        expect.objectContaining({ file, clip_count: 5 }),
        expect.any(Function),
      ),
    );
    expect(push).toHaveBeenCalledWith("/jobs/upload-id");
  });
});
