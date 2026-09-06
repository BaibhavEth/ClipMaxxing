import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";

describe("landing page", () => {
  it("presents the product and links to the creation flow", () => {
    render(<Home />);

    expect(
      screen.getByRole("heading", { name: "Turn long videos into clips worth watching." }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Start clipping" })).toHaveLength(3);
    expect(screen.getByRole("heading", { name: "Copy the YouTube link" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Choose your output" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review and download" })).toBeInTheDocument();
    expect(
      screen.getByAltText("YouTube video page with its URL visible in the browser"),
    ).toBeInTheDocument();
    expect(
      screen.getByAltText("ClipCraft creation page with URL and clip settings"),
    ).toBeInTheDocument();
    expect(
      screen.getByAltText("ClipCraft results showing generated clips with video previews"),
    ).toBeInTheDocument();
  });
});
