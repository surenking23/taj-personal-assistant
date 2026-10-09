# Taj — Personal Assistant

Local-first personal assistant foundation for Windows. The web chat can
browse/read files in a configured workspace, create new files, launch Notepad,
Calculator, or Explorer, and run PowerShell commands after showing the exact
command for explicit approval. Existing-file overwrites and file deletion also
require approval. Every local action is written to the activity log.

This is a useful, bounded first version—not unrestricted autonomous control.
Explicit local commands work without a model. Free-form natural language uses
the official GitHub Copilot CLI by default and authenticates with the user's
Copilot CLI sign-in—no API key is created or extracted. OpenAI and Ollama are
optional provider alternatives. The model can only select from Taj's bounded
local actions; Copilot's built-in tools are disabled for these chat sessions.
Job discovery is wired to the public Arbeitnow and RemoteOK listing APIs;
general-purpose web search, email, calendar, browser form automation, and
external application submission are not connected. Unsupported tasks are
reported as unavailable rather than claimed as complete.

## Run locally

Requirements: Python 3.11+.

1. Create and activate a virtual environment.
2. Install dependencies: `python -m pip install -e ".[dev]"`.
3. Set a unique `JARVIS_API_TOKEN` and optionally `JARVIS_WORKSPACE` to the
   directory the assistant may access. The default workspace is the directory
   from which the server starts. The API reads environment variables directly
   and does not load `.env` files automatically.
4. Install GitHub Copilot CLI on Windows using
   `winget install GitHub.Copilot`. Start `copilot` in a terminal and enter
   `/login`; complete GitHub device authentication with the account that has an
   active Copilot plan. Taj uses the CLI login on the same Windows user
   profile. No Copilot API key is needed or created. Set
   `JARVIS_MODEL_PROVIDER=copilot`; optionally set `COPILOT_MODEL` to a model
   enabled for your account (default `auto`).
   Alternatively, choose OpenAI (`JARVIS_MODEL_PROVIDER=openai` and a
   server-side `OPENAI_API_KEY`) or local Ollama
   (`JARVIS_MODEL_PROVIDER=ollama`, `OLLAMA_MODEL=qwen2.5:3b`).
5. Start on loopback only: `python -m uvicorn jarvis.main:app --app-dir src --host 127.0.0.1 --port 8000`.
6. Open `http://127.0.0.1:8000` and enter the bearer token in the Connection
   panel. Interactive API documentation is at `/docs`.

The visible assistant name is Taj. The `JARVIS_*` environment-variable names,
Python package directory, and `/v1` API paths are retained for compatibility.

## Container deployment preparation

Deployment files are provided, but no image or service has been published.
Docker Desktop with Linux containers and Docker Compose v2 are required.

1. Copy `.env.deploy.example` to `.env.deploy`.
2. Replace both placeholder secrets with separate random 64-character
   hexadecimal values (generate each with
   `python -c "import secrets; print(secrets.token_hex(32))"`). Do not commit
   `.env.deploy`; it is git-ignored.
3. Configure an AI provider. `openai` needs a valid `OPENAI_API_KEY`.
   Alternatively, choose Ollama with `JARVIS_MODEL_PROVIDER=ollama` and an
   `OLLAMA_BASE_URL` reachable from the app container.
4. Build and start with
   `docker compose --env-file .env.deploy -f compose.deploy.yml up --build -d`.
5. Verify `http://127.0.0.1:8000/health`, then open
   `http://127.0.0.1:8000/` and enter `JARVIS_API_TOKEN` from `.env.deploy`.
6. Stop with
   `docker compose --env-file .env.deploy -f compose.deploy.yml down`.
   Postgres, Redis, and workspace data remain in named volumes.

The deployment binds the web port to loopback by default and keeps Postgres and
Redis private to the Docker network. The app runs as a non-root user with a
read-only root filesystem, dropped Linux capabilities, and service health
checks. For public access, terminate TLS at a properly configured reverse proxy
and protect the host with firewall rules; do not bind the app directly to an
untrusted network.

The signed-in GitHub Copilot CLI session belongs to the Windows user profile
and is not copied into the container. The container cannot use that Copilot
login; configure OpenAI or a reachable Ollama provider instead. Its workspace
is a dedicated named volume, not the Windows host workspace. Windows-specific
actions such as launching Notepad/Explorer and PowerShell execution are not
available from this Linux container. Continue using the local Windows run
method for those capabilities.

The original `docker-compose.yml` remains the development Postgres/Redis-only
stack. The deployment stack is in `compose.deploy.yml`.

## Netlify + Render deployment

This repository is wired for Netlify static hosting with the FastAPI service,
PostgreSQL, and Redis on Render. **No site or paid service has been created.**
Render's Blueprint provisions managed services that may incur charges; review
the current plan prices in Render before confirming service creation.

1. Push this repository to a Git provider that both Netlify and Render can
   access.
2. In Render, create a Blueprint from the repository and select `render.yaml`.
   Review the PostgreSQL and Redis service plans and costs before applying.
   Enter `OPENAI_API_KEY` as a secret when prompted; Render generates
   `JARVIS_API_TOKEN`.
3. Wait for the `taj-api` service to become healthy, then copy its HTTPS origin
   (for example, `https://taj-api.onrender.com`).
4. In Netlify, import the same repository with the root directory as the base.
   Set the build environment variable `TAJ_API_URL` to the Render HTTPS origin.
   The repository's `netlify.toml` runs `scripts/prepare_netlify.py`, which
   publishes the static interface and writes Netlify proxy rules for `/v1/*`
   and `/health`.
5. Open the Netlify HTTPS URL, enter the `JARVIS_API_TOKEN` from the Render
   service environment, and check that model status is online. Keep API tokens
   and provider keys only in the provider secret settings; never put them in
   frontend build variables.

The Netlify proxy keeps browser API requests same-origin. The Render API itself
is public at its service URL but requires the bearer token for all `/v1`
routes; `/health` exposes only a basic liveness response. The profile, master
resume, jobs, and activity data will be stored in the Render PostgreSQL service,
not on the Windows PC. Do not migrate private data unless you intend to store it
with Render. This setup does not deploy or expose the local Windows Copilot
login, workspace, browser, or desktop actions.

For local preflight of the Netlify build, set `TAJ_API_URL` to the Render
service's HTTPS origin and run `python scripts/prepare_netlify.py`; the
generated `netlify-dist/` folder is ignored by Git. `python -m pytest -q`
validates the backend separately. Docker and provider-account credentials are
required to publish and verify the hosted services.

## Career foundation (Phase 1)

The authenticated **Career Profile** page stores only information you enter,
including contact details, education, target roles/preferences, and skills.
The **Master Resume** page stores text or Markdown as append-only versions.
Saving changes creates a new version; previous versions remain available and
are checksum-verified. Tailored resumes are not generated yet, so the master
resume is not modified by any automation.

- `GET /v1/profile` and `PUT /v1/profile` — read or replace the structured
  profile.
- `GET /v1/resumes/master` — read the latest saved master resume, or `null`.
- `GET /v1/resumes/master/versions` — list saved version metadata.
- `GET /v1/resumes/master/versions/{id}` — read a specific immutable version.
- `POST /v1/resumes/master/versions` — create a new version with `content`
  and an optional `change_note` (UTF-8 text/Markdown, up to 100 KB).

Both features use the configured SQL database and require the existing bearer
token. A fresh profile starts blank; no personal details or sample skills are
pre-filled. The current local profile has been populated only with the career
targets, skills, locations, education, and project details supplied by Suren;
existing contact fields were preserved. This phase does not yet support
PDF/DOCX parsing, resume tailoring,
or application submission.
Verified project context can be stored in the profile, including project
summaries, tools, focus areas, datasets, repository links, and explicitly
provided metrics. Unknown dates, grades, work authorization, and employment
history remain blank until supplied. International listings are only considered
for countries explicitly entered under "Countries where you are authorized to
work"; an empty field does not imply authorization.

## Job search (Phase 2)

The **Jobs** page and chat commands such as `Find Data Analyst jobs in Chennai`
use real public listing APIs, not generated or sample job data. By default, the
search runs against Arbeitnow and RemoteOK concurrently. Set
`JOB_SEARCH_SOURCES` to a comma-separated subset of `arbeitnow,remoteok` to
configure the providers. A source failure is reported separately while the
other source continues. This is job-listing search, not general web search or
website scraping.

Listings are normalized and deduplicated by their canonical source URL, saved
to the SQL database, analyzed for known required/preferred skills, matched
against the saved career profile and latest master-resume text, and ranked with
a visible skills/role/location/work-mode/experience score breakdown. The
ranking is a transparent heuristic, not an AI guarantee. Missing profile data
is not invented. Scores use fixed weights: skills 60%, target role 25%, and
location, work mode, and experience 5% each. Unknown dimensions contribute zero
instead of inflating a score by reweighting an incomplete profile. If neither a
target role nor search keywords are available, the system asks for them rather
than returning unfiltered listings. Chat job-search requests are routed to the
tool before the AI answer model, so the model cannot answer that a supported
search is unavailable.

- `POST /v1/jobs/search` — search with role, location, work mode, experience,
  skills/keywords, company, salary, minimum match score, and result limit.
  Blank role/location/preferences fall back to the saved profile.
- `GET /v1/jobs` — list saved listings, optionally filter by minimum match score.

Search results include each source's status and errors. An empty provider
response means no matching listings were returned; it is not replaced with
fabricated results. Job-search activity is recorded in `/v1/activity`.
Application preparation, browser-assisted form filling, resume tailoring,
cover-letter generation, and submission are separate phases and are not yet
implemented; submitting a job application is never attempted by this search
tool.

## Supported local actions

- `list files` or `list files in <folder>`
- `read file <relative-path>`
- `create file <relative-path> with <text>`
- `update file <relative-path> with <text>` (approval required)
- `delete file <relative-path>` (approval required)
- `open notepad`, `open calculator`, or `open explorer`
- `run command: <PowerShell command>` (approval required)

When your Copilot account is signed in and the selected model is available, you
can phrase these actions naturally.
The model returns a strict, validated action proposal; it does not directly execute
commands or get access to file contents. Directly supported commands continue
to work when the chat model is unavailable. The chat remembers the last 20
messages in this browser profile; use **New chat** to clear that conversation.

Paths are resolved under `JARVIS_WORKSPACE`, including symlink resolution, and
cannot escape that directory. File reads are limited to 256 KB. PowerShell
commands run in the workspace with a 30-second timeout and bounded output.
Approval is deliberately separate from execution: approve first, then click
**Execute now**. Do not expose the local API to a network or use untrusted
commands; PowerShell can make broad changes to your Windows account.

## Existing API

- `POST /v1/commands` — create an honest specialist plan.
- `POST /v1/assistant/actions` — perform a safe local action or queue an
  approval-gated one.
- `POST /v1/assistant/actions/{id}/execute` — execute only after explicit
  approval.
- `GET /v1/activity` and `GET /v1/approvals` — inspect runs and approvals.
- `/v1/memory` — memory records are hidden until approved.
- `/v1/tasks` — Redis-backed task records.

All `/v1` routes require `Authorization: Bearer <JARVIS_API_TOKEN>`. `/health`
and the local UI are public to the local listener. The single-token model is a
development baseline, not production identity or role-based access control.
Database schema migrations, rate limiting, secret rotation, and operational
monitoring are still needed before any production deployment.

Run tests with `python -m pytest`.
