"""
Scanner Agent — "The Librarian"
Reads the repo structure, README, and package.json to understand
the project: what framework it uses, how to start it, what it does.
"""

import os
import json
import re

from dotenv import load_dotenv
from agents.gemini_client import generate_content_with_fallback

load_dotenv()


IGNORED_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", "dist",
    "build", ".venv", "venv", ".cache", "coverage", ".nyc_output"
}
IGNORED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                      ".lock", ".map", ".min.js", ".min.css"}


def _read_file_safe(path: str, max_bytes: int = 4000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(max_bytes)
    except Exception:
        return ""


def _build_file_tree(root: str) -> list[str]:
    tree = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        rel_dir = os.path.relpath(dirpath, root)
        for f in filenames:
            if not any(f.endswith(ext) for ext in IGNORED_EXTENSIONS):
                tree.append(os.path.join(rel_dir, f) if rel_dir != "." else f)
    return tree[:150]  # Cap at 150 files


def _extract_json(text: str) -> dict:
    """
    Robustly extract JSON from LLM response.
    Handles: raw JSON, ```json fences, JSON embedded in prose.
    """
    # Try stripping markdown fences
    clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    # Try direct parse
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    # Try finding first { ... } block
    m = re.search(r"\{[\s\S]*\}", clean)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def scan_repo(repo_path: str) -> dict:
    """
    Analyzes the repository and returns a dict with:
    - framework: react | nextjs | vue | express | fastapi | django | unknown
    - start_command: how to run the dev server
    - install_command: how to install deps
    - entry_file: main entry point file
    - description: what the app does
    - has_tests: bool
    - env_file_exists: bool
    - dockerfile_exists: bool
    """
    file_tree = _build_file_tree(repo_path)

    # Read key files
    readme = ""
    package_json = ""
    pyproject = ""

    for fname in ["README.md", "readme.md", "README.rst"]:
        p = os.path.join(repo_path, fname)
        if os.path.exists(p):
            readme = _read_file_safe(p, 3000)
            break

    pkg_path = os.path.join(repo_path, "package.json")
    if os.path.exists(pkg_path):
        package_json = _read_file_safe(pkg_path, 2000)

    pyproject_path = os.path.join(repo_path, "pyproject.toml")
    req_path = os.path.join(repo_path, "requirements.txt")
    if os.path.exists(pyproject_path):
        pyproject = _read_file_safe(pyproject_path, 1000)
    elif os.path.exists(req_path):
        pyproject = _read_file_safe(req_path, 1000)

    # Static checks (don't need LLM)
    has_dockerfile = os.path.exists(os.path.join(repo_path, "Dockerfile"))
    has_env_file = any(
        os.path.exists(os.path.join(repo_path, f))
        for f in [".env", ".env.example", ".env.local"]
    )
    has_tests = any(
        "test" in f.lower() or "spec" in f.lower() or "__tests__" in f.lower()
        for f in file_tree
    )

    has_python_files = any(f.endswith(".py") for f in file_tree)
    is_python_project = bool(pyproject) or has_python_files

    framework = "unknown"
    start_command = "npm start"
    install_command = "npm install"

    if package_json:
        try:
            pkg = json.loads(package_json)
            scripts = pkg.get("scripts", {})
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}

            if "next" in deps:
                framework = "nextjs"
                start_command = scripts.get("dev", "npm run dev")
            elif "react" in deps or "react-dom" in deps:
                framework = "react"
                start_command = scripts.get("start", scripts.get("dev", "npm start"))
            elif "vue" in deps:
                framework = "vue"
                start_command = scripts.get("serve", scripts.get("dev", "npm run dev"))
            elif "express" in deps or "koa" in deps:
                framework = "express"
                start_command = scripts.get("start", scripts.get("dev", "node index.js"))

            install_command = "npm install"
        except json.JSONDecodeError:
            pass
    elif is_python_project:
        if pyproject and "fastapi" in pyproject.lower():
            framework = "fastapi"
            start_command = "uvicorn main:app --reload"
            install_command = "pip install -r requirements.txt"
        elif pyproject and "django" in pyproject.lower():
            framework = "django"
            start_command = "python manage.py runserver"
            install_command = "pip install -r requirements.txt"
        elif pyproject and "flask" in pyproject.lower():
            framework = "flask"
            start_command = "python app.py"
            install_command = "pip install -r requirements.txt"
        else:
            # Generic Python scripts / ML repos (no web server)
            start_command = ""
            if "requirements.txt" in file_tree:
                install_command = "pip install -r requirements.txt"
            else:
                install_command = ""

    has_web_server = (framework != "unknown") or bool(package_json)

    # Use LLM only for description and entry file (less critical)
    description = "A web application"
    entry_file = "src/index.js"

    try:
        prompt = f"""Analyze this repository and return ONLY valid JSON (no markdown, no explanation).

File tree (first 50 files):
{chr(10).join(file_tree[:50])}

README (first 1500 chars):
{readme[:1500]}

Return this exact JSON structure:
{{
  "description": "one sentence describing what this app does",
  "entry_file": "the main entry point file path",
  "likely_port": 3000
}}"""
        response = generate_content_with_fallback(prompt)
        parsed = _extract_json(response.text)
        description = parsed.get("description", description)
        entry_file = parsed.get("entry_file", entry_file)

    except Exception as e:
        print(f"[Scanner] LLM call failed (using static analysis only): {e}")

    return {
        "framework": framework,
        "start_command": start_command,
        "install_command": install_command,
        "entry_file": entry_file,
        "description": description,
        "file_tree": file_tree[:80],
        "has_tests": has_tests,
        "env_file_exists": has_env_file,
        "dockerfile_exists": has_dockerfile,
        "has_package_json": bool(package_json),
        "is_python": is_python_project,
        "has_web_server": has_web_server,
    }
