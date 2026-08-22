"""
CLI runner used by GitHub Actions.
Usage: python run_job.py <repo_url> <job_id>

Runs the full analysis pipeline and writes the result to a JSON file
so GitHub Actions can upload it as an artifact.
"""

import sys
import json
import os
import warnings

# Suppress Google API core Python version deprecation warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core")

# Reconfigure console streams to use UTF-8 on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

from orchestrator import run_analysis


def main():
    if len(sys.argv) < 3:
        print("Usage: python run_job.py <repo_url> <job_id>")
        sys.exit(1)

    repo_url = sys.argv[1]
    job_id = sys.argv[2]

    print(f"[Runner] Starting analysis for: {repo_url}")
    print(f"[Runner] Job ID: {job_id}")

    jobs = {
        job_id: {
            "status": "running",
            "logs": [],
            "result": None,
            "error": None,
        }
    }

    run_analysis(job_id, repo_url, jobs)

    job = jobs[job_id]
    print(f"\n[Runner] Status: {job['status']}")

    if job["error"]:
        print(f"[Runner] Error: {job['error']}")

    output_file = f"result_{job_id}.json"
    with open(output_file, "w") as f:
        result_summary = {}
        if job.get("result"):
            r = job["result"]
            result_summary = {
                "repo_url": r.get("repo_url"),
                "framework": r.get("scan", {}).get("framework"),
                "bugs_found": len(r.get("bugs", [])),
                "arch_issues": len(r.get("architecture", {}).get("static_issues", [])),
                "fixes_generated": len(r.get("diffs", [])),
                "logs": job["logs"],
                "status": job["status"],
            }
        json.dump(result_summary, f, indent=2)

    print(f"[Runner] Result written to {output_file}")

    if job["status"] == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
