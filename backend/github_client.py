"""
GitHub API client helper — Dhruv's file.
Wraps PyGithub for common operations used across the project.
"""

import os
import re
from github import Github, GithubException
from dotenv import load_dotenv

load_dotenv()


def get_client() -> Github:
    """Return an authenticated GitHub client."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise EnvironmentError(
            "GITHUB_TOKEN is not set. Add it to backend/.env\n"
            "Get one at: github.com → Settings → Developer Settings → Personal Access Tokens"
        )
    return Github(token)


def parse_repo_name(repo_url: str) -> str:
    """
    Extract 'owner/repo' from any GitHub URL format.
    Handles:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
    """
    match = re.search(r"github\.com[/:]([^/]+/[^/\s\.]+)", repo_url)
    if not match:
        raise ValueError(f"Cannot parse GitHub repo name from: {repo_url}")
    return match.group(1)


def repo_is_accessible(repo_url: str) -> bool:
    """Check if we can access the given repo with our token."""
    try:
        g = get_client()
        name = parse_repo_name(repo_url)
        g.get_repo(name)
        return True
    except GithubException:
        return False


def trigger_workflow(
    our_repo_name: str,
    repo_url_to_analyze: str,
    job_id: str,
    workflow_file: str = "agent-runner.yml",
    branch: str = "main",
) -> bool:
    """
    Trigger the agent-runner GitHub Actions workflow via API.
    Use this if you want to run analysis in GitHub Actions instead of locally.
    """
    try:
        g = get_client()
        repo = g.get_repo(our_repo_name)
        workflow = repo.get_workflow(workflow_file)
        workflow.create_dispatch(
            ref=branch,
            inputs={
                "repo_url": repo_url_to_analyze,
                "job_id": job_id,
            }
        )
        print(f"[GitHub] Triggered workflow for job {job_id}")
        return True
    except GithubException as e:
        print(f"[GitHub] Failed to trigger workflow: {e.data.get('message', str(e))}")
        return False


def get_workflow_run_status(our_repo_name: str, job_id: str) -> dict:
    """
    Poll the status of a running workflow.
    Returns dict with: status, conclusion, html_url
    """
    try:
        g = get_client()
        repo = g.get_repo(our_repo_name)
        runs = repo.get_workflow_runs(workflow_id="agent-runner.yml", branch="main")
        for run in runs:
            return {
                "status": run.status,
                "conclusion": run.conclusion,
                "html_url": run.html_url,
            }
    except Exception as e:
        print(f"[GitHub] Could not get workflow status: {e}")
    return {"status": "unknown", "conclusion": None, "html_url": None}
