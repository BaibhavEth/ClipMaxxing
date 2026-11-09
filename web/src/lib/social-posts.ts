export type SocialStyle = "quote" | "story" | "breakdown";

export type SocialPosts = Record<SocialStyle, string>;

export const SOCIAL_STYLES: { style: SocialStyle; label: string }[] = [
  { style: "quote", label: "Quote" },
  { style: "story", label: "Story" },
  { style: "breakdown", label: "Breakdown" },
];

export function parseSocialPosts(value: string | null | undefined): SocialPosts {
  if (!value) {
    return { quote: "", story: "", breakdown: "" };
  }
  try {
    const parsed = JSON.parse(value) as {
      quote?: unknown;
      story?: unknown;
      breakdown?: unknown;
    };
    if (parsed && typeof parsed === "object" && typeof parsed.quote === "string") {
      return {
        quote: parsed.quote,
        story: typeof parsed.story === "string" ? parsed.story : "",
        breakdown: typeof parsed.breakdown === "string" ? parsed.breakdown : "",
      };
    }
  } catch {
    // Older clips stored a single quote-style post as plain text.
  }
  return { quote: value, story: "", breakdown: "" };
}
