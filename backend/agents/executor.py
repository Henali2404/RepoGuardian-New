"""
Executor Agent — "The PR Bot"
1. generate_diffs(): For each fixable bug, asks Gemini to produce the fixed file.
   Returns structured diffs the frontend can display.
2. push_pr(): Creates a GitHub branch, commits the fixes, opens a Pull Request.
"""

import os
import re
import json

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


def generate_diffs(bugs: list, repo_path: str) -> list:
    """
    For each bug, generate the fixed file content.
    Returns list of diff objects.
    """
    diffs = []

    # Emit one remediation record for every detected issue. Issues without a
    # readable file remain visible with their suggested manual fix.
    fixable = bugs

    for bug in fixable:
        file_path = bug.get("file") or "unknown"
        original_content = _read_file(repo_path, file_path) if file_path != "unknown" else None
        if original_content is None:
            diffs.append({
            "file": file_path,
                "original": "",
                "fixed": "",
                "bug": bug,
                "success": False,
                "error": "Automatic patch unavailable: source file could not be read.",
            })
            continue

        prompt = f"""You are a code fixing assistant. Fix the following bug in this file.

BUG:
- File: {bug['file']}
- Line: {bug.get('line_number', 'unknown')}
- Type: {bug['error_type']}
- Description: {bug['error_description']}
- Suggested fix: {bug['suggested_fix']}
- Problematic code: {bug.get('code_snippet', '')}

ORIGINAL FILE CONTENT:
{original_content}
Return ONLY the complete fixed file content, with NO explanation, NO markdown fences, NO preamble.
Just the raw fixed code that can be directly written to the file.
Make the minimal change needed to fix the specific bug described. Do not refactor unrelated code."""

        try:
            response = generate_content_with_fallback(prompt)
            fixed_content = _extract_code_from_response(response.text, original_content)

            diffs.append({
                "file": bug["file"],
                "original": original_content,
                "fixed": fixed_content,
                "bug": bug,
                "success": True,
                "error": None,
            })

        except Exception as e:
            diffs.append({
                "file": bug["file"],
                "original": original_content,
                "fixed": original_content,  # No change on failure
                "bug": bug,
                "success": False,
                "error": str(e),
            })

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
