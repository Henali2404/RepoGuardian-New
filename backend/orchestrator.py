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

        # Merge findings from advanced scanner
        scanner_findings = scan_result.get("scanner_findings", {})
        scanner_bugs = scanner_findings.get("bugs", [])
        scanner_security_findings = scanner_findings.get("security_findings", [])

        # Merge bugs
        existing_keys = {(b.get("file"), b.get("line_number")) for b in bugs if b.get("file") and b.get("line_number")}
        for sb in scanner_bugs:
            key = (sb.get("file"), sb.get("line_number"))
            if key not in existing_keys:
                bugs.append(sb)

        # Merge security findings
        if security_report and scanner_security_findings:
            for sf in scanner_security_findings:
                check_id = sf.get("check_id", "")
                severity = sf.get("severity", "warning").lower()
                
                # Check 1: Secrets
                if check_id == "SEC-001":
                    sec_key = "check_1_secrets"
                    if sec_key not in security_report:
                        security_report[sec_key] = {"findings": [], "summary": "", "secrets_found": 0, "critical_count": 0}
                    if not any(f.get("file_name") == sf["file_name"] and f.get("line_hint") == sf["line_hint"] for f in security_report[sec_key]["findings"]):
                        security_report[sec_key]["findings"].append(sf)
                        security_report[sec_key]["secrets_found"] = security_report[sec_key].get("secrets_found", 0) + 1
                        if severity == "critical":
                            security_report[sec_key]["critical_count"] = security_report[sec_key].get("critical_count", 0) + 1
                            
                # Check 3: Pre-deploy
                elif check_id in ("SEC-006", "CONF-001"):
                    sec_key = "check_3_predeploy"
                    if sec_key not in security_report:
                        security_report[sec_key] = {"findings": [], "deploy_ready": True, "blockers": [], "warnings": [], "summary": ""}
                    if not any(f.get("file_name") == sf["file_name"] and f.get("line_hint") == sf["line_hint"] for f in security_report[sec_key]["findings"]):
                        security_report[sec_key]["findings"].append(sf)
                        if severity == "critical":
                            security_report[sec_key]["blockers"].append(sf.get("title"))
                            security_report[sec_key]["deploy_ready"] = False
                        else:
                            security_report[sec_key]["warnings"].append(sf.get("title"))
                            
                # Check 4: Deep Logic Audit
                elif check_id in ("SEC-002", "SEC-003", "SEC-004", "SEC-005", "BUG-001"):
                    sec_key = "check_4_deep"
                    if sec_key not in security_report:
                        security_report[sec_key] = {"findings": [], "critical_paths": [], "summary": "", "exploitable_count": 0}
                    if not any(f.get("file_name") == sf["file_name"] and f.get("line_hint") == sf["line_hint"] for f in security_report[sec_key]["findings"]):
                        security_report[sec_key]["findings"].append(sf)
                        security_report[sec_key]["exploitable_count"] = security_report[sec_key].get("exploitable_count", 0) + 1
                        if severity in ("critical", "high"):
                            security_report[sec_key]["critical_paths"].append(sf.get("title"))
                            
                # Check 5: Attacker View
                else:
                    sec_key = "check_5_attacker"
                    if sec_key not in security_report:
                        security_report[sec_key] = {"findings": [], "attack_surface": [], "summary": "", "critical_attack_paths": 0}
                    if not any(f.get("file_name") == sf["file_name"] and f.get("line_hint") == sf["line_hint"] for f in security_report[sec_key]["findings"]):
                        security_report[sec_key]["findings"].append(sf)
                        if severity in ("critical", "high"):
                            security_report[sec_key]["critical_attack_paths"] = security_report[sec_key].get("critical_attack_paths", 0) + 1
                            security_report[sec_key]["attack_surface"].append(sf.get("title"))

            # Recalculate security report totals
            total_findings = 0
            critical_total = 0
            for sec_key in ["check_1_secrets", "check_2_data_flow", "check_3_predeploy", "check_4_deep", "check_5_attacker"]:
                if sec_key in security_report:
                    flist = security_report[sec_key].get("findings", [])
                    total_findings += len(flist)
                    for f in flist:
                        if f.get("severity") == "critical":
                            critical_total += 1
            security_report["total_findings"] = total_findings
            security_report["critical_total"] = critical_total

        # Recalculate scores based on merged findings
        if scores:
            criticals = sum(1 for b in bugs if b.get("severity") == "critical")
            warnings = sum(1 for b in bugs if b.get("severity") == "warning")
            infos = sum(1 for b in bugs if b.get("severity") == "info")
            
            score = 100 - (criticals * 15) - (warnings * 5) - (infos * 2)
            score = max(0, score)
            
            scores["health"] = min(scores.get("health", 100), score)
            scores["code_quality"] = min(scores.get("code_quality", 100), max(0, score - 5))
            scores["maintainability"] = min(scores.get("maintainability", 100), max(0, score - 5))
            scores["security"] = min(scores.get("security", 100), max(0, score - 10) if criticals > 0 else score)

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

        # Merge architecture issues from advanced scanner
        scanner_static_issues = scanner_findings.get("static_issues", [])
        if arch_result and scanner_static_issues:
            existing_arch_keys = {(i.get("file"), i.get("line"), i.get("title")) for i in arch_result.get("static_issues", [])}
            for si in scanner_static_issues:
                key = (si.get("file"), si.get("line"), si.get("title"))
                if key not in existing_arch_keys:
                    arch_result["static_issues"].append(si)
            
            # Recalculate summary and scores
            static_issues = arch_result.get("static_issues", [])
            arch_result["summary"] = {
                "critical": sum(1 for i in static_issues if i.get("severity") == "critical"),
                "warnings": sum(1 for i in static_issues if i.get("severity") == "warning"),
                "info": sum(1 for i in static_issues if i.get("severity") == "info"),
            }
            
            score = 100
            for issue in static_issues:
                severity = issue.get("severity", "warning")
                if severity == "critical":
                    score -= 15
                elif severity == "warning":
                    score -= 5
                elif severity == "info":
                    score -= 2
            arch_result["score"] = max(0, score)

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
