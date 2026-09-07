import type {
  ApiKeyStatus,
  ClipEditSettings,
  CreateJobInput,
  Job,
  ProjectSummary,
  TranscriptWord,
} from "@/lib/types";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function authorizedHeaders(includeJson = false): Promise<HeadersInit> {
  const {
    data: { session },
  } = await createClient().auth.getSession();
  if (!session?.access_token) {
    throw new Error("Sign in required");
  }
  return {
    Authorization: `Bearer ${session.access_token}`,
    ...(includeJson ? { "Content-Type": "application/json" } : {}),
  };
}

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
    headers: await authorizedHeaders(true),
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
    headers: await authorizedHeaders(),
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
    { cache: "no-store", headers: await authorizedHeaders() },
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
      headers: await authorizedHeaders(true),
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
    { method: "POST", headers: await authorizedHeaders() },
  );
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { text: string };
  return payload.text;
}

export async function getProjects(): Promise<ProjectSummary[]> {
  const response = await fetch(`${API_URL}/api/projects`, {
    cache: "no-store",
    headers: await authorizedHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { projects: ProjectSummary[] };
  return payload.projects;
}

export async function getOpenAIKeyStatus(): Promise<ApiKeyStatus> {
  const response = await fetch(`${API_URL}/api/account/openai-key`, {
    cache: "no-store",
    headers: await authorizedHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json() as Promise<ApiKeyStatus>;
}

export async function saveOpenAIKey(apiKey: string): Promise<ApiKeyStatus> {
  const response = await fetch(`${API_URL}/api/account/openai-key`, {
    method: "PUT",
    headers: await authorizedHeaders(true),
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return response.json() as Promise<ApiKeyStatus>;
}

export async function deleteOpenAIKey(): Promise<void> {
  const response = await fetch(`${API_URL}/api/account/openai-key`, {
    method: "DELETE",
    headers: await authorizedHeaders(),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
}
