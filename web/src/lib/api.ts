import type {
  ClipEditSettings,
  CreateJobInput,
  Job,
  ProjectSummary,
  TranscriptWord,
  UploadJobInput,
} from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const JSON_HEADERS = { "Content-Type": "application/json" };

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
    headers: JSON_HEADERS,
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { id: string };
  return payload.id;
}

export function uploadJob(
  input: UploadJobInput,
  onProgress?: (fraction: number) => void,
): Promise<string> {
  const form = new FormData();
  form.append("file", input.file);
  form.append("clip_count", String(input.clip_count));
  form.append("target_duration", String(input.target_duration));
  form.append("render", JSON.stringify(input.render));

  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_URL}/api/uploads`);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    request.onerror = () => reject(new Error("The processing service is unavailable"));
    request.onload = () => {
      let payload: { id?: string; detail?: string } = {};
      try {
        payload = JSON.parse(request.responseText) as typeof payload;
      } catch {
        // Fall through to the generic error below.
      }
      if (request.status >= 200 && request.status < 300 && payload.id) {
        resolve(payload.id);
      } else {
        reject(new Error(payload.detail ?? "The upload failed"));
      }
    };
    request.send(form);
  });
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
      headers: JSON_HEADERS,
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
): Promise<{ text: string; story_text: string; breakdown_text: string }> {
  const response = await fetch(
    `${API_URL}/api/jobs/${encodeURIComponent(jobId)}/clips/${encodeURIComponent(
      filename,
    )}/social-post`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as {
    text: string;
    story_text?: string;
    breakdown_text?: string;
  };
  return {
    text: payload.text,
    story_text: payload.story_text ?? "",
    breakdown_text: payload.breakdown_text ?? "",
  };
}

export async function getProjects(): Promise<ProjectSummary[]> {
  const response = await fetch(`${API_URL}/api/projects`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { projects: ProjectSummary[] };
  return payload.projects;
}
