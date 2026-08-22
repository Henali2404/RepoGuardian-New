"""
Executor Agent — "The PR Bot"
1. generate_diffs(): For each fixable bug, asks Gemini to produce the fixed file.
   Returns structured diffs the frontend can display.
2. push_pr(): Creates a GitHub branch, commits the fixes, opens a Pull Request.
"""

import os
import re
import json
import subprocess

from dotenv import load_dotenv
from github import Github, GithubException
from agents.gemini_client import generate_content_with_fallback

load_dotenv()

IGNORED_DIRS = {"node_modules", ".git", "__pycache__", ".next", "dist", "build"}


def _read_file(repo_path: str, rel_path: str) -> str | None:
    """Read a source file relative to the repo root."""
    full_path = os.path.join(repo_path, rel_path)
    if not os.path.exists(full_path):
        return None
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


def _extract_code_from_response(response_text: str, original: str) -> str:
    """
    Extract clean code from an LLM response.
    Handles markdown fences, explanations before/after code, etc.
    Falls back to original if extraction fails.
    """
    text = response_text.strip()

    # Try to extract from ```language ... ``` fences
    fence_match = re.search(r"```(?:\w+)?\n([\s\S]+?)```", text)
    if fence_match:
        return fence_match.group(1).strip()

    # Try to find code-like content (starts with import/const/def/class/function etc.)
    code_start = re.search(
        r"^(import |from |const |let |var |function |class |def |export |<!DOCTYPE|<html|#!)",
        text, re.MULTILINE
    )
    if code_start:
        return text[code_start.start():].strip()

    # If response is short and contains explanation text, don't use it
    if len(text) < len(original) * 0.3:
        return original  # LLM returned too little — keep original

    return text


def _extract_replacement(response_text: str) -> str:
    """Extract a replacement block without requiring it to resemble a full file."""
    text = response_text.strip("\r\n")
    fence_match = re.search(r"```(?:\w+)?\n([\s\S]+?)```", text)
    return fence_match.group(1).strip("\r\n") if fence_match else text


def _validate_candidate(repo_path: str, file_path: str, candidate: str, old_block: str) -> tuple[bool, str]:
    """Validate a candidate and reject it when the original target remains."""
    if old_block.strip() and old_block in candidate:
        return False, "The original issue block is still present after the patch."
    full_path = os.path.join(repo_path, file_path)
    try:
        with open(full_path, "w", encoding="utf-8") as file:
            file.write(candidate)
        if file_path.endswith(".py"):
            result = subprocess.run(["python", "-m", "py_compile", full_path], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return False, result.stderr.strip() or "Python syntax validation failed."
        elif file_path.endswith((".js", ".mjs", ".cjs")):
            result = subprocess.run(["node", "--check", full_path], capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return False, result.stderr.strip() or "JavaScript syntax validation failed."
        return True, "Patch applied and validation passed."
    except (OSError, subprocess.SubprocessError) as error:
        return False, f"Validation failed: {error}"


def generate_diffs(fix_plans: list, repo_path: str) -> list:
    """Generate and validate small replacements described by Architect plans."""
    diffs = []
    for plan in fix_plans:
        finding = plan.get("finding", plan.get("bug", {}))
        file_path = plan.get("file") or finding.get("file") or "unknown"
        original_content = _read_file(repo_path, file_path) if file_path != "unknown" else None
        if original_content is None:
            diffs.append({"file": file_path, "original": "", "fixed": "", "bug": finding, "plan": plan,
                          "success": False, "error": "Automatic patch unavailable: source file could not be read."})
            continue

        prompt = f"""You are a code fixing assistant. Apply only this verified fix plan.
FIX PLAN:
{json.dumps(plan, indent=2)}
TARGETED CODE CONTEXT:
{finding.get('relevant_code_context', finding.get('code_snippet', ''))}
Return ONLY replacement code for lines {plan.get('start_line')} through {plan.get('end_line')}.
Do not return the complete file, line numbers, markdown fences, or an explanation."""

        try:
            response = generate_content_with_fallback(prompt)
            replacement = _extract_replacement(response.text)
            lines = original_content.splitlines(keepends=True)
            start = max(1, int(plan.get("start_line", 1)))
            end = min(len(lines), int(plan.get("end_line", start)))
            old_block = "".join(lines[start - 1:end])
            newline = "" if replacement.endswith(("\n", "\r")) else "\n"
            fixed_content = "".join(lines[:start - 1]) + replacement + newline + "".join(lines[end:])
            valid, validation_message = _validate_candidate(repo_path, file_path, fixed_content, old_block)
            if not valid:
                with open(os.path.join(repo_path, file_path), "w", encoding="utf-8") as file:
                    file.write(original_content)
            diffs.append({"file": file_path, "original": original_content,
                          "fixed": fixed_content if valid else original_content, "bug": finding, "plan": plan,
                          "success": valid, "validation": {"passed": valid, "message": validation_message},
                          "error": None if valid else validation_message})
        except Exception as error:
            diffs.append({"file": file_path, "original": original_content, "fixed": original_content,
                          "bug": finding, "plan": plan, "success": False, "error": str(error)})
    return diffs


def push_pr(job_result: dict) -> str:
    """
    Create a GitHub branch with the fixes and open a Pull Request.
    Returns the PR URL.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable not set")

    repo_url = job_result["repo_url"]
    diffs = job_result.get("diffs", [])
    bugs = job_result.get("bugs", [])
    arch = job_result.get("architecture", {})

    # Parse repo name from URL
    match = re.search(r"github\.com[/:]([^/]+/[^/\.]+)", repo_url)
    if not match:
        raise ValueError(f"Could not parse GitHub repo from URL: {repo_url}")
    repo_name = match.group(1)

    g = Github(token)
    try:
        repo = g.get_repo(repo_name)
    except GithubException as e:
        raise ValueError(f"Could not access repo {repo_name}: {e.data.get('message', str(e))}")

    # Get default branch
    default_branch = repo.default_branch
    base_sha = repo.get_branch(default_branch).commit.sha

    # Create fix branch
    branch_name = "auto-fix/autonomous-architect"
    try:
        repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)
    except GithubException as e:
        if e.status == 422:  # Branch already exists
            ref = repo.get_git_ref(f"heads/{branch_name}")
            ref.delete()
            repo.create_git_ref(f"refs/heads/{branch_name}", base_sha)
        else:
            raise

    # Commit each fix
    committed_files = []
    for diff in diffs:
        if not diff.get("success"):
            continue
        if diff["original"] == diff["fixed"]:
            continue  # No actual change

        try:
            file_obj = repo.get_contents(diff["file"], ref=default_branch)
            repo.update_file(
                path=diff["file"],
                message=f"fix: {diff['bug']['error_description'][:72]}",
                content=diff["fixed"],
                sha=file_obj.sha,
                branch=branch_name,
            )
            committed_files.append(diff["file"])
        except GithubException as e:
            print(f"[Executor] Could not commit {diff['file']}: {e}")
        except Exception as e:
            print(f"[Executor] Error committing {diff['file']}: {e}")

    bug_lines = []
    for b in bugs[:10]:
        line_str = f" (line {b['line_number']})" if b.get('line_number') else ""
        bug_lines.append(f"- **{b['error_type']}** in `{b['file']}`{line_str}: {b['error_description']}")
    bug_list = "\n".join(bug_lines)

    arch_issues = arch.get("static_issues", [])
    arch_list = "\n".join(
        f"- [{i['type'].upper()}] {i['title']}"
        for i in arch_issues[:5]
    )

    files_changed = "\n".join(f"- `{f}`" for f in committed_files) or "_(no files were automatically fixed)_"

    pr_body = f"""## 🤖 Autonomous Architect — Auto-Generated Fix

This Pull Request was created automatically by the **Autonomous Code Architect** agent.

> ⚠️ **Review all changes carefully before merging.** AI-generated fixes may need adjustment.

---

### 🐛 Bugs Found ({len(bugs)})
{bug_list or "_No runtime bugs detected_"}

### 📁 Files Changed
{files_changed}

### 🏗️ Architecture Issues Detected ({len(arch_issues)})
{arch_list or "_No architecture issues detected_"}

---
*Generated by Autonomous Architect • Always review AI-generated code before merging*"""

    if not committed_files:
        report_content = f"# Autonomous Architect Report\n\n{pr_body}"
        try:
            repo.create_file(
                ".autonomous-architect-report.md",
                "docs: add autonomous architect analysis report",
                report_content,
                branch=branch_name,
            )
            committed_files.append(".autonomous-architect-report.md")
        except Exception:
            pass

    # Create the Pull Request
    pr = repo.create_pull(
        title=f"🤖 Auto-fix: {len(bugs)} bug(s) found by Autonomous Architect",
        body=pr_body,
        head=branch_name,
        base=default_branch,
    )

    return pr.html_url
