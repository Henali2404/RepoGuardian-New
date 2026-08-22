# RepoGuardian

RepoGuardian is a full-stack repository analysis workspace. It accepts a public GitHub repository, runs a multi-agent audit, captures runtime issues, produces security and architecture findings, and can generate a fix branch and pull request after approval.

## What It Does

The backend coordinates these agents:

1. **Scanner** identifies the repository framework, dependencies, and start command.
2. **Explorer** installs dependencies, runs the target application, and captures browser and console errors with Playwright.
3. **Auditor** maps runtime errors to source files and line numbers.
4. **Architect** reviews security, architecture, and performance risks.
5. **Market Agent** adds product and market context to the analysis.
6. **Executor** prepares code changes and can open a GitHub pull request after approval.

The frontend provides authentication, analysis progress, reports, analysis history, pull request history, and account settings.

## Stack

- **Frontend:** Next.js App Router, React, TypeScript, Tailwind CSS, Supabase Auth
- **Backend:** FastAPI, Uvicorn, Pydantic, HTTPX, SSE
- **Analysis:** Python agents, Playwright, GitPython, PyGithub, Gemini or Ollama
- **Persistence:** Supabase PostgreSQL

## Project Layout

```text
.
├── backend/
│   ├── agents/              # Scanner, explorer, auditor, architect, market, executor
│   ├── main.py              # FastAPI application and API routes
│   ├── orchestrator.py      # Analysis workflow coordinator
│   ├── db.py                # Supabase database client
│   ├── run_job.py           # Job runner utilities
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── app/                 # Login, analysis, dashboard, history, reports, settings
│   ├── components/          # Shared UI and authentication components
│   ├── lib/                 # Supabase client and backend API client
│   ├── package.json
│   └── .env.local.example
├── supabase/
│   └── schema.sql           # Database tables, indexes, and auth profile trigger
├── demo-broken-app/         # Small app for testing the analysis workflow
├── create_demo_repo.py      # Publishes the demo app to GitHub
└── run.bat                  # Starts both local development servers on Windows
```

## Prerequisites

- Python 3.10 or newer
- Node.js 18 or newer
- Git
- A Supabase project
- A GitHub token that can read repositories and create pull requests
- Either a Gemini API key or a local Ollama installation

## Configuration

### Backend

From the repository root:

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
```

Set these values in `backend/.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:3b
GEMINI_API_KEY=your-gemini-key
GITHUB_TOKEN=your-github-token
FRONTEND_URL=http://localhost:3000
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_SERVICE_KEY=your-supabase-service-role-key
```

Use `LLM_PROVIDER=gemini` with `GEMINI_API_KEY` when using Gemini. Keep `.env` files private and never expose `SUPABASE_SERVICE_KEY` or GitHub tokens to the browser.

Optional performance settings are documented in `backend/.env.example`. Response caching is bounded and can be disabled with `LLM_CACHE_ENABLED=false`. Gemini security checks run concurrently by default; set `AUDITOR_PARALLEL_SECURITY=false` to force sequential checks, which can be useful for a constrained local provider.

Start the API from the `backend` directory:

```powershell
uvicorn main:app --reload --port 8000
```

The API is available at `http://localhost:8000`. FastAPI's interactive documentation is available at `http://localhost:8000/docs`.

### Frontend

In a second terminal, from the repository root:

```powershell
cd frontend
npm install
copy .env.local.example .env.local
```

Set the frontend values in `frontend/.env.local`. The Supabase URL and anon key must belong to the same project as the backend values:

```env
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-key
```

Start the web application:

```powershell
npm run dev
```

Open `http://localhost:3000`.

## Database Setup

Run [`supabase/schema.sql`](supabase/schema.sql) in the Supabase SQL Editor before using registration, analysis history, reports, or pull request history. The schema creates profiles, analysis jobs, reports, diffs, and PR history, plus the trigger that creates a profile after signup.

## Run Both Services on Windows

After installing backend and frontend dependencies, run this from the repository root:

```powershell
.\run.bat
```

It opens separate command windows for the backend at `http://localhost:8000` and frontend at `http://localhost:3000`.

## Demo Repository

The `demo-broken-app` directory contains a deliberately broken React app for exercising the scanner and runtime-error workflow. To publish it to your GitHub account:

```powershell
python create_demo_repo.py
```

The script uses the `GITHUB_TOKEN` configured in `backend/.env`. Paste the resulting repository URL into the analysis page.

## Frontend Commands

Run these from `frontend`:

```powershell
npm run dev       # Start the development server
npm run build     # Create a production build
npm run start     # Serve the production build
npm run lint      # Run Next.js linting
```

## Security Notes

- Do not commit `backend/.env` or `frontend/.env.local`.
- Only the Supabase anon key belongs in frontend public configuration.
- Keep the Supabase service-role key, GitHub token, and model API keys in the backend environment.
- Rotate credentials immediately if they are pasted into an issue, chat, screenshot, or commit.
