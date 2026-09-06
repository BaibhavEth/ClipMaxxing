import type {
  ClipEditSettings,
  CreateJobInput,
  Job,
  TranscriptWord,
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    return payload.detail ?? "Something went wrong";
  } catch {
    return "The processing service is unavailable";
  }
}

export async function createJob(input: CreateJobInput): Promise<string> {
  const response = await fetch(`${API_URL}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { id: string };
  return payload.id;
}

export async function getJob(jobId: string): Promise<Job> {
  const response = await fetch(`${API_URL}/api/jobs/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json() as Promise<Job>;
}

export async function getClipTranscript(
  jobId: string,
  filename: string,
): Promise<TranscriptWord[]> {
  const response = await fetch(
    `${API_URL}/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(
      filename,
    )}/transcript`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { words: TranscriptWord[] };
  return payload.words;
}

export async function renderClip(
  jobId: string,
  filename: string,
  settings: ClipEditSettings,
): Promise<void> {
  const response = await fetch(
    `${API_URL}/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(
      filename,
    )}/render`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings }),
    },
  );
  if (!response.ok) {
    throw new Error(await readError(response));
  }
}

export async function generateSocialPost(
  jobId: string,
  filename: string,
): Promise<string> {
  const response = await fetch(
    `${API_URL}/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(
      filename,
    )}/social-post`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { text: string };
  return payload.text;
}
