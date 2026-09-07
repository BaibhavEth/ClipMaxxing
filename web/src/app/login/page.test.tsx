import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LoginPage from "@/app/login/page";

describe("login page", () => {
  it("offers Google and email magic-link sign in", () => {
    render(<LoginPage />);

    expect(
      screen.getByRole("heading", { name: "Sign in to your workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Email me a sign-in link" }),
    ).toBeInTheDocument();
  });
});
