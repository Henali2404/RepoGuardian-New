"""
Orchestrator: chains all 6 agents in sequence.
Each agent logs to jobs[job_id]["logs"] in real-time so the frontend
can stream progress via SSE.
"""

import tempfile
import subprocess
import shutil
import os
import time

import db
from agents.scanner import scan_repo
from agents.explorer import explore_app
from agents.auditor import audit_errors
from agents.architect import analyze_architecture
from agents.executor import generate_diffs
from agents.market_agent import analyze_market


class AnalysisStopped(Exception):
    """Raised when a user requests cancellation between pipeline stages."""


def check_cancelled(jobs: dict, job_id: str):
    job = jobs.get(job_id)
    if not job or (job.get("cancel_event") and job["cancel_event"].is_set()):
        raise AnalysisStopped()


def log(jobs: dict, job_id: str, agent: str, message: str, level: str = "info"):
    """Append a structured log entry. Frontend reads this in real-time."""
    jobs[job_id]["logs"].append({
        "agent": agent,
        "message": message,
        "level": level,  # info | warning | error | success
    })
    print(f"[{agent}] {message}")  # Also print to server console


def run_analysis(job_id: str, repo_url: str, jobs: dict, user_id: str | None = None):
    """
    Main pipeline. Runs in a background thread (FastAPI BackgroundTasks).
    Updates jobs[job_id] throughout so SSE stream sees live progress.
    """
    tmp_path = None
    try:
        check_cancelled(jobs, job_id)
        # ── STEP 1: Clone the repo ──────────────────────────────────────────
        try:
            db.create_job_record(job_id, repo_url, user_id=user_id)
        except Exception as db_init_err:
            print(f"[Orchestrator] Initial DB job record creation failed: {db_init_err}")

        tmp_path = tempfile.mkdtemp(prefix="architect_")
        jobs[job_id]["tmp_path"] = tmp_path
        log(jobs, job_id, "Scanner", f"Cloning repository: {repo_url}")

        clone_process = subprocess.Popen(
            ["git", "clone", "--depth", "1", repo_url, tmp_path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        while clone_process.poll() is None:
            job = jobs.get(job_id)
            if not job or (job.get("cancel_event") and job["cancel_event"].is_set()):
                clone_process.terminate()
                clone_process.wait(timeout=5)
                raise AnalysisStopped()
            time.sleep(0.2)
        clone_stdout, clone_stderr = clone_process.communicate()
        clone_result = subprocess.CompletedProcess(
            clone_process.args, clone_process.returncode, clone_stdout, clone_stderr,
        )
        if clone_result.returncode != 0:
            raise ValueError(f"Git clone failed: {clone_result.stderr.strip()}")

        log(jobs, job_id, "Scanner", "Repository cloned successfully ✓", "success")

        # ── STEP 2: Scanner Agent ──────────────────────────────────────────
        check_cancelled(jobs, job_id)
        log(jobs, job_id, "Scanner", "Analyzing file structure, README, and dependencies...")
        scan_result = scan_repo(tmp_path)
        log(jobs, job_id, "Scanner",
            f"Detected: {scan_result.get('framework', 'unknown')} app. "
            f"Start command: {scan_result.get('start_command', 'unknown')} ✓", "success")

        # ── STEP 3: Explorer Agent ─────────────────────────────────────────
        check_cancelled(jobs, job_id)
        log(jobs, job_id, "Explorer", "Installing dependencies (this may take a minute)...")
        explorer_result = explore_app(
            tmp_path, scan_result, jobs, job_id,
            is_cancelled=lambda: job_id not in jobs or jobs[job_id]["cancel_event"].is_set(),
        )
        error_count = len(explorer_result.get("console_errors", []))
        screenshot_b64 = explorer_result.get("screenshot_b64")
        log(jobs, job_id, "Explorer",
            f"Exploration complete. Found {error_count} console error(s) ✓", "success")

        # ── STEP 4: Auditor Agent ──────────────────────────────────────────
        check_cancelled(jobs, job_id)
        log(jobs, job_id, "Auditor", "Mapping errors to source code lines...")
        bugs, scores, security_report = audit_errors(explorer_result, tmp_path)
        try:
            db.save_scores(job_id, scores)
            db.save_security_report(job_id, security_report)
        except Exception as db_err:
            print(f"[Orchestrator] Database save failed for auditor: {db_err}")

        log(jobs, job_id, "Auditor",
            f"Identified {len(bugs)} fixable bug(s) in source code ✓", "success")

        # ── STEP 5: Architect Agent ────────────────────────────────────────
        check_cancelled(jobs, job_id)
        log(jobs, job_id, "Architect", "Scanning for performance, security & architecture issues...")
        arch_result = analyze_architecture(tmp_path, scan_result)
        issue_count = len(arch_result.get("static_issues", []))
        log(jobs, job_id, "Architect",
            f"Found {issue_count} static issue(s). AI analysis complete ✓", "success")

        # ── STEP 6: Executor Agent ─────────────────────────────────────────
        check_cancelled(jobs, job_id)
        if bugs:
            log(jobs, job_id, "Executor", f"Generating code diffs for {len(bugs)} bug(s)...")
            diffs = generate_diffs(bugs, tmp_path)
            log(jobs, job_id, "Executor",
                f"Generated {len(diffs)} fix(es). Awaiting human approval ✓", "success")
        else:
            diffs = []
            log(jobs, job_id, "Executor", "No bugs to fix — skipping diff generation", "info")

        # ── STEP 7: Market Agent ───────────────────────────────────────────
        check_cancelled(jobs, job_id)
        log(jobs, job_id, "Market", "Analyzing market potential and competitive landscape...")
        market_report = analyze_market(tmp_path, scan_result)
        try:
            db.save_market_report(job_id, market_report)
        except Exception as db_err:
            print(f"[Orchestrator] Database save failed for market report: {db_err}")

        log(jobs, job_id, "Market", f"Viability score: {market_report.get('viability_score', 0)}/100 ✓", "success")

        # ── DONE ───────────────────────────────────────────────────────────
        log(jobs, job_id, "System",
            "Analysis complete! Review the findings and click 'Approve & Push PR' to create the Pull Request.",
            "success")

        jobs[job_id]["status"] = "done"
        jobs[job_id]["scores"] = scores
        jobs[job_id]["security_report"] = security_report
        jobs[job_id]["market_report"] = market_report
        jobs[job_id]["screenshot_b64"] = screenshot_b64
        
        jobs[job_id]["result"] = {
            "repo_url": repo_url,
            "tmp_path": tmp_path,
            "scan": scan_result,
            "explorer": explorer_result,
            "bugs": bugs,
            "architecture": arch_result,
            "diffs": diffs,
            "scores": scores,
            "security_report": security_report,
            "market_report": market_report,
            "screenshot_b64": screenshot_b64,
        }

        # Save complete job record & artifacts to Supabase DB
        try:
            db.save_bug_reports(job_id, bugs)
            db.save_architecture_issues(job_id, arch_result)
            if screenshot_b64:
                db.save_screenshot(job_id, screenshot_b64)
            db.save_analysis_snapshot(job_id, jobs[job_id]["result"], jobs[job_id]["logs"])
            db.save_analysis_diffs(job_id, diffs)
            db.save_analysis_workflow(job_id)
            db.update_job_status(
                job_id=job_id,
                status="done",
                framework=scan_result.get("framework"),
                health_score=scores.get("health") if isinstance(scores, dict) else None,
                user_id=user_id,  # backfill user_id in case create_job_record missed it
            )
            print(f"[Orchestrator] Successfully saved job {job_id} to Supabase!")
        except Exception as db_save_err:
            print(f"[Orchestrator] Final Supabase DB update failed: {db_save_err}")

    except AnalysisStopped:
        if job_id not in jobs:
            return
        jobs[job_id]["status"] = "stopped"
        log(jobs, job_id, "System", "Analysis stopped by user.", "warning")
        try:
            db.update_job_status(job_id=job_id, status="stopped", user_id=user_id)
        except Exception as db_err:
            print(f"[Orchestrator] Failed to persist stopped status: {db_err}")
        if tmp_path and os.path.exists(tmp_path):
            shutil.rmtree(tmp_path, ignore_errors=True)
    except Exception as e:
        if job_id not in jobs:
            return
        error_msg = str(e)
        log(jobs, job_id, "System", f"Pipeline failed: {error_msg}", "error")
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = error_msg
        # Clean up on failure
        if tmp_path and os.path.exists(tmp_path):
            shutil.rmtree(tmp_path, ignore_errors=True)
