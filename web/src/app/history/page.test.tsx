import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HistoryPage from "@/app/history/page";
import { getProjects } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  getProjects: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("history page", () => {
  it("shows projects owned by the signed-in user", async () => {
    vi.mocked(getProjects).mockResolvedValue([
      {
        id: "project-id",
        source_url: "https://youtu.be/example",
        title: "Founder interview",
        status: "complete",
        progress: 100,
        message: "Created 5 clips",
        error: null,
        clip_count: 5,
        target_duration: 45,
        created_at: "2026-09-06T10:00:00Z",
        updated_at: "2026-09-06T10:10:00Z",
      },
    ]);

    render(<HistoryPage />);

    expect(await screen.findByText("Founder interview")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open project" })).toHaveAttribute(
      "href",
      "/jobs/project-id",
    );
  });
});
