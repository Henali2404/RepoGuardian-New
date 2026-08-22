import asyncio
import json
import uuid
import os
import sys
import warnings
import threading
from pathlib import Path

# Suppress Google API core Python version deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# Set Windows Event Loop Policy to Proactor to support Playwright subprocesses
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Reconfigure console streams to use UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from fastapi import FastAPI, BackgroundTasks, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

from orchestrator import run_analysis
from agents.executor import push_pr

app = FastAPI(title="Autonomous Architect API")
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory job store — fine for hackathon demo
# Key: job_id, Value: { status, logs, result }
jobs: dict = {}


def require_user(authorization: str | None = Header(default=None)) -> dict:
    """Validate a Supabase access token and return its user payload."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1].strip()
    try:
        import db
        user_response = db.get_db().auth.get_user(token)
        user = getattr(user_response, "user", None)
        if not user:
            raise ValueError("Invalid token")
        return {"id": user.id, "email": user.email}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")


def require_stream_user(token: str | None) -> dict:
    return require_user(f"Bearer {token}" if token else None)


class SignupRequest(BaseModel):
    email: str
    password: str
    full_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdate(BaseModel):
    full_name: str


def parse_json_field(value):
    """Decode JSON stored as text while leaving native JSON values unchanged."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


@app.post("/auth/signup")
async def signup(req: SignupRequest):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Authentication is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{url}/auth/v1/signup",
            headers={"apikey": key, "Content-Type": "application/json"},
            json={"email": req.email, "password": req.password, "data": {"display_name": req.full_name}},
        )
    if response.status_code >= 400:
        response_data = response.json()
        response_text = str(response_data).lower()
        if "already" in response_text or "registered" in response_text or "email_exists" in response_text:
            raise HTTPException(status_code=409, detail="An account with this email already exists. Please log in instead.")
        safe_detail = response_data.get("msg") or response_data.get("message") or "Unable to create account"
        raise HTTPException(status_code=response.status_code, detail=safe_detail)
    return {"message": "Account created. Please sign in."}


@app.post("/auth/login")
async def login(req: LoginRequest):
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Authentication is not configured")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{url}/auth/v1/token?grant_type=password",
            headers={"apikey": key, "Content-Type": "application/json"},
            json={"email": req.email, "password": req.password},
        )
    if response.status_code >= 400:
        response_text = response.text.lower()
        if "user not found" in response_text or "no user" in response_text or "user_not_found" in response_text:
            raise HTTPException(status_code=404, detail="No account found. Please create an account first.")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return response.json()


@app.post("/auth/logout", status_code=204)
async def logout(user: dict = Depends(require_user)):
    return None


@app.get("/auth/me")
async def me(user: dict = Depends(require_user)):
    return user


@app.get("/api/profile")
def get_profile(user: dict = Depends(require_user)):
    """Return only the authenticated user's profile."""
    try:
        import db
        result = db.get_db().table("profiles").select("id,email,display_name,created_at").eq("id", user["id"]).single().execute()
        return result.data or {"id": user["id"], "email": user["email"], "display_name": ""}
    except Exception:
        return {"id": user["id"], "email": user["email"], "display_name": ""}


@app.patch("/api/profile")
def update_profile(req: ProfileUpdate, user: dict = Depends(require_user)):
    """Update only the authenticated user's profile."""
    full_name = req.full_name.strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="Full name must contain at least 2 characters")
    try:
        import db
        result = db.get_db().table("profiles").update({"display_name": full_name}).eq("id", user["id"]).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Profile not found")
        return result.data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to update profile")


class AnalyzeRequest(BaseModel):
    repo_url: str
    user_id: str | None = None


class ApproveRequest(BaseModel):
    job_id: str


@app.get("/")
def root():
    return {"status": "Autonomous Architect API is running"}


@app.post("/api/analyze")
async def start_analysis(req: AnalyzeRequest, background_tasks: BackgroundTasks, user: dict = Depends(require_user)):
    """Start a new analysis job. Returns job_id immediately."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": "running",
        "logs": [],
        "result": None,
        "error": None,
        "user_id": user["id"],
        "cancel_event": threading.Event(),
    }
    background_tasks.add_task(run_analysis, job_id, req.repo_url, jobs, user["id"])
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
async def stream_status(job_id: str, token: str | None = Query(default=None)):
    """
    Server-Sent Events stream.
    Frontend connects here and receives live updates until job is done/error.
    """
    user = require_stream_user(token)
    if job_id not in jobs or jobs[job_id].get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        last_log_count = 0
        while True:
            job = jobs.get(job_id, {})
            if not job:
                break
            current_logs = job.get("logs", [])

            # Only send new logs since last tick (efficient)
            new_logs = current_logs[last_log_count:]
            last_log_count = len(current_logs)

            payload = {
                "status": job.get("status", "running"),
                "new_logs": new_logs,
                "all_logs": current_logs,
                "result": job.get("result"),
                "error": job.get("error"),
                "scores": job.get("scores"),
                "security_report": job.get("security_report"),
                "market_report": job.get("market_report"),
                "screenshot_b64": job.get("screenshot_b64"),
            }
            yield {"data": json.dumps(payload)}

            status = job.get("status")
            if status in ("done", "error", "stopped"):
                break

            await asyncio.sleep(0.8)

    return EventSourceResponse(event_generator())


@app.get("/api/job/{job_id}")
def get_job(job_id: str, user: dict = Depends(require_user)):
    """Polling fallback if SSE doesn't work (e.g. some proxies block it)."""
    if job_id in jobs:
        if jobs[job_id].get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Job not found")
        return {key: value for key, value in jobs[job_id].items() if key not in ("cancel_event", "tmp_path")}
    try:
        import db
        stored = db.get_job_full(job_id)
        job = stored.get("job", {})
        if not job or job.get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "status": job.get("status", "done"),
            "logs": [],
            "result": {
                "repo_url": job.get("repo_url", ""),
                "scan": {"framework": job.get("framework", "Unknown")},
                "bugs": stored.get("bugs", []),
                "architecture": {"static_issues": stored.get("architecture_issues", []), "ai_analysis": stored.get("ai_analysis", {}).get("markdown_report", "") if stored.get("ai_analysis") else ""},
                "diffs": [],
                "scores": job.get("scores"),
                "security_report": job.get("security_report"),
                "market_report": job.get("market_report"),
            },
            "error": job.get("error_message"),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")


@app.get("/api/jobs/user/{user_id}")
def get_user_jobs_endpoint(user_id: str, limit: int = 20, user: dict = Depends(require_user)):
    """Fetch previously entered URLs / jobs for a specific user from Supabase."""
    if user_id != user["id"]:
        raise HTTPException(status_code=403, detail="You can only access your own jobs")
    try:
        import db
        return db.get_user_jobs(user_id, limit=limit)
    except Exception as e:
        print(f"[API] Failed to fetch user jobs for {user_id}: {e}")
        return []


@app.get("/api/analysis/{job_id}")
def get_analysis(job_id: str, user: dict = Depends(require_user)):
    """Return a completed analysis exactly as it was persisted."""
    try:
        import db
        stored = db.get_job_full(job_id)
        job = stored.get("job", {})
        if not job or job.get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Analysis not found")

        result = parse_json_field(job.get("analysis_result"))
        if not isinstance(result, dict):
            result = None
        if not result:
            result = {
                "repo_url": job.get("repo_url", ""),
                "scan": {"framework": job.get("framework", "Unknown")},
                "bugs": [{
                    "file": bug.get("file_path", "unknown"),
                    "line_number": bug.get("line_number"),
                    "error_type": bug.get("error_type", "Error"),
                    "error_description": bug.get("error_description", ""),
                    "code_snippet": bug.get("code_snippet", ""),
                    "suggested_fix": bug.get("suggested_fix", ""),
                    "severity": bug.get("severity", "warning"),
                } for bug in stored.get("bugs", [])],
                "architecture": {
                    "static_issues": [{
                        "type": issue.get("issue_type", "general"),
                        "severity": issue.get("severity", "warning"),
                        "title": issue.get("title", ""),
                        "description": issue.get("description", ""),
                        "suggestion": issue.get("suggestion", ""),
                        "file": issue.get("file_path"),
                        "line": issue.get("line_number"),
                    } for issue in stored.get("architecture_issues", [])],
                    "ai_analysis": stored.get("ai_analysis", {}).get("markdown_report", "") if stored.get("ai_analysis") else "",
                },
                "diffs": stored.get("diffs", []),
                "scores": job.get("scores"),
                "security_report": stored.get("security_report"),
                "market_report": parse_json_field(job.get("market_report")),
                "screenshot_b64": job.get("screenshot_b64"),
            }
        else:
            result["architecture"] = parse_json_field(result.get("architecture"))
            result["market_report"] = parse_json_field(result.get("market_report") or job.get("market_report"))
            result["security_report"] = parse_json_field(result.get("security_report") or job.get("security_report"))
            if not isinstance(result.get("bugs"), list):
                result["bugs"] = result.get("issues") if isinstance(result.get("issues"), list) else []
            if not isinstance(result.get("diffs"), list):
                result["diffs"] = result.get("fixes") if isinstance(result.get("fixes"), list) else []
        if not result.get("diffs") and stored.get("diffs"):
            result["diffs"] = stored["diffs"]
        if not result.get("diffs") and result.get("bugs"):
            result["diffs"] = [{
                "file": bug.get("file") or "unknown",
                "original": "",
                "fixed": "",
                "bug": bug,
                "success": False,
                "error": "Automatic patch was not saved for this historical analysis.",
            } for bug in result["bugs"] if isinstance(bug, dict)]
        if not result.get("architecture"):
            architecture_issues = stored.get("architecture_issues", [])
            result["architecture"] = {
                "static_issues": [{
                    "type": issue.get("issue_type", "general"),
                    "severity": issue.get("severity", "warning"),
                    "title": issue.get("title", ""),
                    "description": issue.get("description", ""),
                    "suggestion": issue.get("suggestion", ""),
                    "file": issue.get("file_path"),
                    "line": issue.get("line_number"),
                } for issue in architecture_issues],
                "ai_analysis": stored.get("ai_analysis", {}).get("markdown_report", "") if stored.get("ai_analysis") else "",
                "summary": {
                    "critical": sum(1 for issue in architecture_issues if issue.get("severity") == "critical"),
                    "warnings": sum(1 for issue in architecture_issues if issue.get("severity") == "warning"),
                    "info": sum(1 for issue in architecture_issues if issue.get("severity") == "info"),
                },
                "score": 0,
            }
        response_payload = {
            "status": job.get("status", "done"),
            "logs": job.get("trace_logs") or [],
            "trace_logs": job.get("trace_logs") or [],
            "traceLogs": job.get("trace_logs") or [],
            "result": result,
            "error": job.get("error_message"),
            "scores": result.get("scores") or job.get("scores"),
            "security_report": result.get("security_report") or job.get("security_report"),
            "market_report": result.get("market_report") or job.get("market_report"),
            "screenshot_b64": result.get("screenshot_b64") or job.get("screenshot_b64"),
            "approval_status": job.get("approval_status", "pending"),
            "push_status": job.get("push_status", "not_pushed"),
            "pr_url": job.get("pr_url") or (stored.get("pr") or {}).get("pr_url"),
        }
        print(
            f"[API] analysis {job_id}: status={response_payload['status']} "
            f"bugs={len(result.get('bugs', []))} diffs={len(result.get('diffs', []))} "
            f"architecture={len(result.get('architecture', {}).get('static_issues', [])) if isinstance(result.get('architecture'), dict) else 0} "
            f"market={bool(response_payload['market_report'])}"
        )
        return response_payload
    except HTTPException:
        raise
    except Exception as error:
        print(f"[API] Failed to load analysis {job_id}: {error}")
        raise HTTPException(status_code=404, detail="Analysis not found")


@app.post("/api/analysis/{job_id}/stop")
def stop_analysis(job_id: str, user: dict = Depends(require_user)):
    """Request cooperative cancellation of an analysis owned by the user."""
    job = jobs.get(job_id)
    if job:
        if job.get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.get("status") != "running":
            raise HTTPException(status_code=400, detail="Analysis is not running")
        job["cancel_event"].set()
        return {"status": "stopping"}

    try:
        import db
        if db.mark_job_stopped(job_id, user["id"]):
            return {"status": "stopped"}
    except Exception as error:
        print(f"[API] Failed to stop job {job_id}: {error}")
    raise HTTPException(status_code=404, detail="Job not found")


@app.delete("/api/analysis/{job_id}")
def delete_analysis(job_id: str, user: dict = Depends(require_user)):
    """Delete an analysis and all related cascade-owned records."""
    job = jobs.get(job_id)
    if job and job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job and job.get("status") == "running":
        job["cancel_event"].set()
    temp_path = (job or {}).get("tmp_path") or (job or {}).get("result", {}).get("tmp_path")
    try:
        import db
        if not db.delete_job_owned(job_id, user["id"]):
            if not job:
                raise HTTPException(status_code=404, detail="Job not found")
    except HTTPException:
        raise
    except Exception as error:
        print(f"[API] Failed to delete job {job_id}: {error}")
        raise HTTPException(status_code=500, detail="Unable to delete analysis")
    jobs.pop(job_id, None)
    if temp_path:
        import shutil
        shutil.rmtree(temp_path, ignore_errors=True)
    return {"deleted": job_id}



@app.post("/api/approve/{job_id}")
async def approve_and_push(job_id: str, user: dict = Depends(require_user)):
    """
    Human-in-the-loop gate.
    User clicks 'Approve' on frontend → this creates the real GitHub PR.
    """
    job = jobs.get(job_id)
    if not job:
        try:
            import db
            stored = db.get_job_full(job_id)
            persisted_job = stored.get("job", {})
            if not persisted_job or persisted_job.get("user_id") != user["id"]:
                raise HTTPException(status_code=404, detail="Job not found")
            persisted_result = persisted_job.get("analysis_result") or {}
            if not persisted_result.get("diffs"):
                persisted_result["diffs"] = stored.get("diffs", [])
            job = {
                "user_id": persisted_job.get("user_id"),
                "status": persisted_job.get("status", "done"),
                "result": persisted_result,
            }
        except HTTPException:
            raise
        except Exception as error:
            print(f"[API] Failed to restore analysis {job_id} for approval: {error}")
            raise HTTPException(status_code=404, detail="Job not found")
    if job.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get("status") != "done":
        raise HTTPException(status_code=400, detail="Job not complete yet")
    if not job.get("result"):
        raise HTTPException(status_code=400, detail="No result to push")

    result = job["result"]
    if not result.get("diffs"):
        return {"message": "No fixable bugs found — nothing to push", "pr_url": None}

    try:
        pr_url = push_pr(result)
        if job_id in jobs:
            jobs[job_id]["pr_url"] = pr_url
        
        # Save PR record in Supabase
        try:
            import db
            db.save_pr_record(
                job_id=job_id,
                user_id=job.get("user_id"),
                repo_url=result.get("repo_url", ""),
                pr_url=pr_url,
                pr_title="Fix repository bugs via RepoGuardian AI",
                branch_name="fix/repoguardian-autofix",
                files_changed=[d["file"] for d in result.get("diffs", []) if "file" in d],
                bugs_fixed=len(result.get("diffs", [])),
            )
            db.save_analysis_workflow(job_id, approval_status="approved", push_status="pushed", pr_url=pr_url)
        except Exception as db_pr_err:
            print(f"[API] Failed to save PR record to DB: {db_pr_err}")

        return {"pr_url": pr_url, "message": "Pull Request created successfully!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create PR: {str(e)}")


@app.delete("/api/job/{job_id}")
def cleanup_job(job_id: str, user: dict = Depends(require_user)):
    """Clean up temp files and job data after demo."""
    job = jobs.get(job_id)
    if job and job.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="You can only delete your own jobs")
    job = jobs.pop(job_id, None)
    if job and job.get("result", {}) and job["result"].get("tmp_path"):
        import shutil
        try:
            shutil.rmtree(job["result"]["tmp_path"], ignore_errors=True)
        except Exception:
            pass
    return {"deleted": job_id}


@app.get("/api/screenshot/{job_id}")
def get_screenshot(job_id: str, user: dict = Depends(require_user)):
    # Try in-memory first
    if job_id in jobs and jobs[job_id].get("user_id") == user["id"]:
        screenshot_b64 = jobs[job_id].get("screenshot_b64")
        if screenshot_b64:
            return {"screenshot_b64": screenshot_b64}
    
    # Try database
    try:
        import db
        job_data = db.get_job_full(job_id)
        if job_data and job_data.get("job", {}).get("user_id") == user["id"]:
            screenshot_b64 = job_data["job"].get("screenshot_b64")
            if screenshot_b64:
                return {"screenshot_b64": screenshot_b64}
    except Exception as e:
        print(f"[API] Failed to get screenshot from DB: {e}")
        
    raise HTTPException(status_code=404, detail="Screenshot not found")
