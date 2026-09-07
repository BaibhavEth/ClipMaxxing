import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SettingsPage from "@/app/settings/page";
import { getOpenAIKeyStatus } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  deleteOpenAIKey: vi.fn(),
  getOpenAIKeyStatus: vi.fn(),
  saveOpenAIKey: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

describe("settings page", () => {
  it("shows the masked configured OpenAI key", async () => {
    vi.mocked(getOpenAIKeyStatus).mockResolvedValue({
      configured: true,
      last4: "1234",
    });

    render(<SettingsPage />);

    expect(await screen.findByText("Configured ····1234")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace key" })).toBeInTheDocument();
    expect(screen.queryByText(/sk-/)).not.toBeInTheDocument();
  });
});
