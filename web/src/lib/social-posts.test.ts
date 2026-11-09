import { describe, expect, it } from "vitest";

import { parseSocialPosts } from "@/lib/social-posts";

describe("social posts", () => {
  it("reads every style from stored json", () => {
    expect(
      parseSocialPosts(
        JSON.stringify({
          quote: "Hook…\n\n“Quote”",
          story: "Setup\n\nturn\n\nkicker",
          breakdown: "Hook\n\npoint\n\nclose?",
        }),
      ),
    ).toEqual({
      quote: "Hook…\n\n“Quote”",
      story: "Setup\n\nturn\n\nkicker",
      breakdown: "Hook\n\npoint\n\nclose?",
    });
  });

  it("leaves the breakdown empty for posts saved before it existed", () => {
    expect(parseSocialPosts(JSON.stringify({ quote: "q", story: "s" }))).toEqual({
      quote: "q",
      story: "s",
      breakdown: "",
    });
  });

  it("treats older plain-text posts as quote style", () => {
    expect(parseSocialPosts("Gold quietly created a business…\n\n“Exact quote.”")).toEqual({
      quote: "Gold quietly created a business…\n\n“Exact quote.”",
      story: "",
      breakdown: "",
    });
  });
});
