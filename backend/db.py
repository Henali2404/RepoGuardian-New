"""
Supabase database layer.
All DB reads/writes go through this module.
Backend uses the service_role key so it can write on behalf of any user
without being blocked by Row Level Security.
"""

import os
from pathlib import Path
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

_client: Client | None = None


def get_db() -> Client:
    """Return a singleton Supabase client."""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in backend/.env"
            )
        _client = create_client(url, key)
    return _client


def create_job_record(job_id: str, repo_url: str, user_id: str | None) -> dict:
    """Insert a new job row when analysis starts."""
    import re
    match = re.search(r"github\.com[/:]([^/\s\.]+/[^/\s\.]+)", repo_url)
    repo_name = match.group(1) if match else repo_url

    db = get_db()
    result = db.table("analysis_jobs").insert({
        "id": job_id,
        "user_id": user_id,
        "repo_url": repo_url,
        "repo_name": repo_name,
        "status": "running",
    }).execute()
    return result.data[0] if result.data else {}


def update_job_status(
    job_id: str,
    status: str,
    framework: str | None = None,
    health_score: int | None = None,
    error_message: str | None = None,
    user_id: str | None = None,
):
    """Update job status when it finishes. Also backfills user_id if provided."""
    from datetime import datetime, timezone
    db = get_db()
    payload: dict = {"status": status}
    if status in ("done", "error", "stopped"):
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    if framework:
        payload["framework"] = framework
    if health_score is not None:
        payload["health_score"] = health_score
    if error_message:
        payload["error_message"] = error_message[:1000]
    if user_id:
        payload["user_id"] = user_id

    db.table("analysis_jobs").update(payload).eq("id", job_id).execute()


def delete_job_owned(job_id: str, user_id: str) -> bool:
    """Delete one job only when it belongs to the authenticated user."""
    db = get_db()
    existing = db.table("analysis_jobs").select("id").eq("id", job_id).eq("user_id", user_id).execute()
    if not existing.data:
        return False
    db.table("analysis_jobs").delete().eq("id", job_id).eq("user_id", user_id).execute()
    return True


def mark_job_stopped(job_id: str, user_id: str) -> bool:
    """Mark a user's running job as stopped."""
    from datetime import datetime, timezone
    db = get_db()
    existing = db.table("analysis_jobs").select("id,status").eq("id", job_id).eq("user_id", user_id).execute()
    if not existing.data or existing.data[0].get("status") != "running":
        return False
    db.table("analysis_jobs").update({"status": "stopped", "completed_at": datetime.now(timezone.utc).isoformat()}).eq("id", job_id).eq("user_id", user_id).execute()
    return True


def save_bug_reports(job_id: str, bugs: list) -> int:
    """Insert all bugs for a job."""
    if not bugs:
        return 0
    db = get_db()
    rows = []
    for bug in bugs:
        if not isinstance(bug, dict):
            continue
        rows.append({
            "job_id": job_id,
            "file_path": str(bug.get("file", "unknown"))[:500],
            "line_number": bug.get("line_number") if isinstance(bug.get("line_number"), int) else None,
            "error_type": str(bug.get("error_type", "Error"))[:100],
            "error_description": str(bug.get("error_description", ""))[:1000],
            "code_snippet": str(bug.get("code_snippet", ""))[:2000],
            "suggested_fix": str(bug.get("suggested_fix", ""))[:2000],
            "severity": bug.get("severity") if bug.get("severity") in ("critical", "warning", "info") else "warning",
        })
    if not rows:
        return 0
    result = db.table("bug_reports").insert(rows).execute()
    return len(result.data) if result.data else 0


def save_architecture_issues(job_id: str, arch_result: dict) -> int:
    """Insert architecture issues and AI analysis."""
    db = get_db()
    static_issues = arch_result.get("static_issues", [])
    ai_analysis = arch_result.get("ai_analysis", "")
    summary = arch_result.get("summary", {})

    rows = []
    for issue in static_issues:
        if not isinstance(issue, dict):
            continue
        rows.append({
            "job_id": job_id,
            "issue_type": str(issue.get("type", "general"))[:50],
            "severity": issue.get("severity") if issue.get("severity") in ("critical", "warning", "info") else "warning",
            "title": str(issue.get("title", ""))[:200],
            "description": str(issue.get("description", ""))[:1000],
            "suggestion": str(issue.get("suggestion", ""))[:1000],
            "file_path": str(issue.get("file", ""))[:500] if issue.get("file") else None,
            "line_number": issue.get("line") if isinstance(issue.get("line"), int) else None,
        })
    count = 0
    if rows:
        result = db.table("architecture_issues").insert(rows).execute()
        count = len(result.data) if result.data else 0

    if ai_analysis:
        db.table("ai_analyses").insert({
            "job_id": job_id,
            "markdown_report": ai_analysis[:10000],
            "critical_count": summary.get("critical", 0),
            "warning_count": summary.get("warnings", 0),
            "info_count": summary.get("info", 0),
        }).execute()

    return count


def save_pr_record(
    job_id: str,
    user_id: str | None,
    repo_url: str,
    pr_url: str,
    pr_title: str,
    branch_name: str,
    files_changed: list[str],
    bugs_fixed: int,
) -> dict:
    """Insert a PR history record."""
    db = get_db()
    result = db.table("pr_history").insert({
        "job_id": job_id,
        "user_id": user_id,
        "repo_url": repo_url,
        "pr_url": pr_url,
        "pr_title": pr_title,
        "branch_name": branch_name,
        "files_changed": files_changed,
        "bugs_fixed": bugs_fixed,
    }).execute()
    return result.data[0] if result.data else {}


def get_user_jobs(user_id: str, limit: int = 20) -> list:
    """Fetch recent jobs for a user."""
    db = get_db()
    result = (
        db.table("analysis_jobs")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_job_full(job_id: str) -> dict:
    """Fetch complete job with all related data."""
    db = get_db()

    job_res = db.table("analysis_jobs").select("*").eq("id", job_id).execute()
    job = job_res.data[0] if job_res.data else None
    if not job:
        return {}

    bugs = db.table("bug_reports").select("*").eq("job_id", job_id).execute().data or []
    arch = db.table("architecture_issues").select("*").eq("job_id", job_id).execute().data or []
    ai_res = db.table("ai_analyses").select("*").eq("job_id", job_id).execute()
    ai = ai_res.data[0] if ai_res.data else None
    security_res = db.table("security_reports").select("report").eq("job_id", job_id).execute()
    security = security_res.data[0].get("report") if security_res.data else job.get("security_report")
    pr_res = db.table("pr_history").select("*").eq("job_id", job_id).execute()
    pr = pr_res.data[0] if pr_res.data else None
    try:
        diff_res = db.table("analysis_diffs").select("diff").eq("job_id", job_id).order("created_at").execute()
        diffs = [row.get("diff") for row in (diff_res.data or []) if row.get("diff")]
    except Exception as error:
        print(f"[DB] Failed to load diffs for {job_id}: {error}")
        diffs = []

    return {
        "job": job,
        "bugs": bugs,
        "architecture_issues": arch,
        "ai_analysis": ai,
        "security_report": security,
        "diffs": diffs,
        "pr": pr,
    }


def save_analysis_snapshot(job_id: str, result: dict, logs: list):
    """Persist the exact completed result and trace shown by the analysis UI."""
    db = get_db()
    snapshot = {key: value for key, value in result.items() if key != "tmp_path"}
    db.table("analysis_jobs").update({
        "analysis_result": snapshot,
        "trace_logs": logs,
    }).eq("id", job_id).execute()


def save_analysis_workflow(job_id: str, approval_status: str = "pending", push_status: str = "not_pushed", pr_url: str | None = None):
    """Persist approval, push, and PR state for historical analysis views."""
    payload = {"approval_status": approval_status, "push_status": push_status}
    if pr_url is not None:
        payload["pr_url"] = pr_url
    get_db().table("analysis_jobs").update(payload).eq("id", job_id).execute()


def save_analysis_diffs(job_id: str, diffs: list):
    """Persist generated diffs separately from the result snapshot."""
    rows = [{"job_id": job_id, "diff": diff} for diff in diffs if isinstance(diff, dict)]
    if rows:
        get_db().table("analysis_diffs").insert(rows).execute()


def get_user_pr_history(user_id: str, limit: int = 50) -> list:
    """Fetch all PRs created by a user."""
    db = get_db()
    result = (
        db.table("pr_history")
        .select("*, analysis_jobs(repo_name, framework)")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def save_scores(job_id: str, scores: dict):
    """Update analysis_jobs row with health score and scores JSON if available."""
    db = get_db()
    health_val = scores.get("health") if isinstance(scores.get("health"), int) else None
    try:
        db.table("analysis_jobs").update({
            "health_score": health_val,
            "scores": scores
        }).eq("id", job_id).execute()
    except Exception:
        try:
            db.table("analysis_jobs").update({
                "health_score": health_val
            }).eq("id", job_id).execute()
        except Exception as e:
            print(f"[DB] save_scores failed: {e}")


def save_security_report(job_id: str, security_report: dict):
    """Insert into a security_reports table or store as JSON string in analysis_jobs.security_report column."""
    db = get_db()
    import json
    try:
        db.table("security_reports").insert({
            "job_id": job_id,
            "report": security_report
        }).execute()
    except Exception:
        try:
            db.table("analysis_jobs").update({
                "security_report": security_report
            }).eq("id", job_id).execute()
        except Exception:
            try:
                db.table("analysis_jobs").update({
                    "security_report": json.dumps(security_report)
                }).eq("id", job_id).execute()
            except Exception as e:
                print(f"[DB] save_security_report failed: {e}")


def save_market_report(job_id: str, market_report: dict):
    """Store market report as JSON string in analysis_jobs.market_report column."""
    db = get_db()
    import json
    try:
        db.table("analysis_jobs").update({
            "market_report": market_report
        }).eq("id", job_id).execute()
    except Exception:
        try:
            db.table("analysis_jobs").update({
                "market_report": json.dumps(market_report)
            }).eq("id", job_id).execute()
        except Exception as e:
            print(f"[DB] save_market_report failed: {e}")


def save_screenshot(job_id: str, screenshot_b64: str):
    """Store screenshot base64 in analysis_jobs.screenshot_b64 column."""
    db = get_db()
    try:
        db.table("analysis_jobs").update({
            "screenshot_b64": screenshot_b64
        }).eq("id", job_id).execute()
    except Exception as e:
        print(f"[DB] save_screenshot failed: {e}")
