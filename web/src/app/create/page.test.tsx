import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CreatePage from "@/app/create/page";
import { createJob } from "@/lib/api";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  createJob: vi.fn(),
}));

const mockedCreateJob = vi.mocked(createJob);

describe("create page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a job and moves to its persistent page", async () => {
    mockedCreateJob.mockResolvedValue("job-id");
    render(<CreatePage />);

    fireEvent.change(screen.getByPlaceholderText("https://www.youtube.com/watch?v=..."), {
      target: { value: "https://youtu.be/example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() =>
      expect(mockedCreateJob).toHaveBeenCalledWith({
        url: "https://youtu.be/example",
        clip_count: 5,
        target_duration: 45,
      }),
    );
    expect(push).toHaveBeenCalledWith("/jobs/job-id");
  });

  it("rejects a non-YouTube URL before submitting", async () => {
    render(<CreatePage />);

    fireEvent.change(screen.getByPlaceholderText("https://www.youtube.com/watch?v=..."), {
      target: { value: "https://example.com/video" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("Paste a valid YouTube URL")).toBeInTheDocument();
    expect(mockedCreateJob).not.toHaveBeenCalled();
  });
});
