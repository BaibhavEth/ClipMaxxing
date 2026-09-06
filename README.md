# ClipCraft

ClipCraft is a local YouTube clipping MVP. Paste a public YouTube URL and it will:

1. download the video with `yt-dlp`;
2. split and transcribe the audio with OpenAI;
3. select strong, self-contained moments with a structured AI response;
4. render accurate MP4 clips with `ffmpeg`;
5. show previews, downloads, and a preset clip editor in the web app.

Only process videos you own or have permission to use. You are responsible for complying with
YouTube's terms and applicable copyright law.

## Requirements

- A current Node.js LTS release
- Python 3.11 or newer
- `ffmpeg` available on `PATH`
- An OpenAI API key

On macOS, install ffmpeg with:

```bash
brew install ffmpeg
```

## Setup

```bash
npm install
npm run setup:api
cp .env.example .env
```

Add your key to `.env`:

```dotenv
OPENAI_API_KEY=sk-...
```

Then start both services:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The API runs at
[http://localhost:8000](http://localhost:8000), and interactive API docs are available at
[http://localhost:8000/docs](http://localhost:8000/docs).

The frontend defaults to `http://localhost:8000`. If the API uses another address, create
`web/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Commands

```bash
npm run dev          # run the web app and API
npm run lint         # ESLint and Ruff
npm run test         # Vitest and pytest
npm run build        # production frontend build
npm run dev:web      # frontend only
npm run dev:api      # API only
```

## Project structure

```text
web/                 Next.js interface
api/app/main.py      FastAPI routes
api/app/jobs.py      filesystem job state and pipeline orchestration
api/app/services/    YouTube, OpenAI, and ffmpeg integrations
api/tests/           backend unit tests
api/data/            generated local job data (gitignored)
```

## How processing works

Submitting a URL returns a job ID immediately. FastAPI runs the pipeline in a background thread
and persists progress as JSON under `api/data/`. The frontend polls the job endpoint and displays
the current stage. Audio is encoded as small mono chunks before transcription so long videos do
not exceed upload limits. Source video and temporary audio are removed after clips render.
Completed jobs and clips are retained locally for 24 hours and cleaned up when the API starts or
a new job is submitted. Source video is also retained for that period so edited clips can be
rendered without downloading the video again. Temporary audio chunks are removed after the
initial clips finish.

## Clip editor

Every newly generated clip includes an **Edit clip** action. The focused editor supports:

- trimming within the original clip boundaries;
- original, portrait 9:16, and square 1:1 formats;
- clean, bold, and minimal burned-in caption presets;
- fade-in and fade-out presets;
- light and medium punch zoom presets.

The browser preview approximates crops, captions, and zoom immediately. **Export clip** performs
the final render from the retained source with FFmpeg, then updates the preview and download URL.
Projects made before editor support do not have retained source media and must be recreated before
they can be edited.

## X post copy

Finished clip cards include **Generate X post**. The on-demand OpenAI call produces an editable
Iced Coffee Hour-style hook followed by a strong quote from the selected clip. Quotes are checked
against the clip transcript before they are returned, which prevents rewritten or invented
quotations from being presented as verbatim. The generated draft can be edited and copied directly
from the result card.

## MVP limitations

- Public YouTube videos only; private, age-restricted, region-locked, or DRM-protected media may
  fail.
- Jobs run in the API process. Restarting it interrupts active work.
- Job state and clips are local to one machine.
- Portrait and square formats use a center crop; subject or face tracking is not included.
- The editor uses presets rather than a freeform multi-track timeline.
- No accounts, cloud storage, or billing.
- The OpenAI key stays in the backend and is never sent to the browser.

For a deployable version, replace background tasks and filesystem state with a durable queue,
database, and object storage.
