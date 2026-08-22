"""
Explorer Agent — "The User"
Installs dependencies, starts the dev server, then uses Playwright
to navigate the app like a real user and capture all errors.

Key improvements over naive version:
- Dynamic port detection (doesn't assume port 3001)
- Proper process cleanup
- Handles apps that won't build cleanly
- Captures network errors, not just console errors
- Logs back to the orchestrator in real-time

FIX APPLIED: Added explicit check for playwright install. If chromium
is not installed, the error message now clearly tells you to run
`playwright install chromium` before demo.
"""

import os
import subprocess
import socket
import time
import signal
import sys
import base64
from typing import Optional

from dotenv import load_dotenv
load_dotenv()


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_for_server(port: int, timeout: int = 45, is_cancelled=None) -> bool:
    """Poll until the dev server is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        if is_cancelled and is_cancelled():
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def _run_install(path: str, install_cmd: str, log_fn, is_cancelled=None) -> bool:
    """Run dependency installation. Returns True on success."""
    log_fn("Explorer", f"Running: {install_cmd}")
    try:
        cmd_args = install_cmd if sys.platform == "win32" else install_cmd.split()
        process = subprocess.Popen(
            cmd_args,
            cwd=path,
            capture_output=True,
            text=True,
            shell=(sys.platform == "win32")
        )
        started = time.time()
        while process.poll() is None:
            if is_cancelled and is_cancelled():
                process.terminate()
                process.wait(timeout=5)
                return False
            if time.time() - started > 180:
                process.terminate()
                process.wait(timeout=5)
                log_fn("Explorer", "Install timed out (>3min) — proceeding anyway", "warning")
                return False
            time.sleep(0.2)
        result = process
        if result.returncode != 0:
            log_fn("Explorer", f"Install warning: {result.stderr[-300:] if result.stderr else 'unknown'}", "warning")
            return False
        return True
    except subprocess.TimeoutExpired:
        log_fn("Explorer", "Install timed out (>3min) — proceeding anyway", "warning")
        return False
    except Exception as e:
        log_fn("Explorer", f"Install failed: {e}", "warning")
        return False


def explore_app(
    repo_path: str,
    scan_result: dict,
    jobs: dict,
    job_id: str,
    is_cancelled=None,
) -> dict:
    """
    Start the app and explore it with Playwright.
    Returns dict with console_errors, network_errors, pages_visited, screenshot_b64.
    """
    console_errors = []
    network_errors = []
    pages_visited = []
    screenshot_b64 = None
    server_proc: Optional[subprocess.Popen] = None

    def log_fn(agent, msg, level="info"):
        if job_id not in jobs:
            return
        jobs[job_id]["logs"].append({"agent": agent, "message": msg, "level": level})
        print(f"[{agent}] {msg}")

    # ── Skip server start if not a web application ──────────────────────────
    if not scan_result.get("has_web_server", True):
        log_fn("Explorer", "No web server detected for this project stack. Skipping browser automation and running static checks.", "info")
        return {
            "console_errors": [],
            "network_errors": [],
            "pages_visited": [],
            "screenshot_b64": None,
            "server_started": False,
        }

    install_cmd = scan_result.get("install_command", "npm install")
    start_cmd = scan_result.get("start_command", "npm start")
    framework = scan_result.get("framework", "unknown")
    is_python = scan_result.get("is_python", False)

    # ── Install dependencies ────────────────────────────────────────────────
    if scan_result.get("has_package_json"):
        _run_install(repo_path, install_cmd, log_fn, is_cancelled)
    elif is_python and install_cmd:
        _run_install(repo_path, install_cmd, log_fn, is_cancelled)

    # ── Start the dev server ────────────────────────────────────────────────
    port = _find_free_port()
    log_fn("Explorer", f"Starting dev server on port {port}: {start_cmd}")

    bin_path = os.path.abspath(os.path.join(repo_path, "node_modules", ".bin"))
    env = {
        **os.environ,
        "PORT": str(port),
        "BROWSER": "none",      # Prevent CRA from opening a browser
        "CI": "true",           # Suppress interactive prompts
        "NODE_ENV": "development",
        "PATH": f"{bin_path}{os.pathsep}{os.environ.get('PATH', '')}"
    }

    try:
        cmd_args = start_cmd if sys.platform == "win32" else start_cmd.split()
        log_file_path = os.path.join(repo_path, "server_startup.log")
        log_file = open(log_file_path, "w", encoding="utf-8")
        server_proc = subprocess.Popen(
            cmd_args,
            cwd=repo_path,
            env=env,
            stdout=log_file,
            stderr=log_file,
            preexec_fn=os.setsid if sys.platform != "win32" else None,
            shell=(sys.platform == "win32")
        )

        # Wait for server to come up
        log_fn("Explorer", f"Waiting for server on port {port}...")
        server_ready = _wait_for_server(port, timeout=120, is_cancelled=is_cancelled)
        if is_cancelled and is_cancelled():
            return {"console_errors": [], "network_errors": [], "pages_visited": [], "screenshot_b64": None, "server_started": False}

        if not server_ready:
            log_fn("Explorer",
                   "Server did not start in time. Analyzing static files instead.", "warning")
            return {
                "console_errors": [{
                    "type": "server_error",
                    "text": "Server failed to start — static analysis only",
                    "location": ""
                }],
                "network_errors": [],
                "pages_visited": [],
                "screenshot_b64": None,
                "server_started": False,
            }

        log_fn("Explorer", f"Server is up at http://localhost:{port} ✓", "success")

        # ── Playwright exploration ──────────────────────────────────────────
        try:
            if sys.platform == "win32":
                import asyncio
                try:
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                except Exception as e:
                    print(f"[Explorer] Warning: Failed to set WindowsProactorEventLoopPolicy: {e}")

            from playwright.sync_api import sync_playwright, Error as PlaywrightError

            with sync_playwright() as p:
                # FIX: wrap chromium.launch in its own try/except to give
                # a clear error message if playwright install chromium wasn't run
                try:
                    browser = p.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                except Exception as launch_err:
                    log_fn("Explorer",
                           f"Chromium not installed. Run: playwright install chromium — Error: {launch_err}",
                           "error")
                    console_errors.append({
                        "type": "setup_error",
                        "text": "Chromium browser not found. Run: playwright install chromium",
                        "location": "",
                    })
                    return {
                        "console_errors": console_errors,
                        "network_errors": [],
                        "pages_visited": [],
                        "screenshot_b64": None,
                        "server_started": True,
                    }

                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True,
                )
                page = context.new_page()

                # Capture ALL console messages
                page.on("console", lambda msg: (
                    console_errors.append({
                        "type": msg.type,
                        "text": msg.text,
                        "location": str(msg.location),
                    })
                    if msg.type in ("error", "warning") else None
                ))

                # Capture uncaught exceptions
                page.on("pageerror", lambda exc: console_errors.append({
                    "type": "pageerror",
                    "text": str(exc),
                    "location": "page",
                }))

                # Capture failed network requests
                page.on("requestfailed", lambda req: network_errors.append({
                    "url": req.url,
                    "failure": req.failure or "unknown",
                }))

                base_url = f"http://localhost:{port}"

                # Visit the home page
                try:
                    log_fn("Explorer", f"Navigating to {base_url}")
                    page.goto(base_url, wait_until="load", timeout=30000)
                    pages_visited.append("/")
                    
                    # Wait 3 seconds to let React render cycles and infinite loops execute
                    page.wait_for_timeout(3000)

                    # Take a screenshot for the report
                    import base64
                    screenshot_bytes = page.screenshot(type="png", full_page=False)
                    screenshot_b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
                    log_fn("Explorer", "Home page loaded and screenshot captured ✓")

                    # Also call db.save_screenshot(job_id, screenshot_b64) if db is available
                    try:
                        import db
                        db.save_screenshot(job_id, screenshot_b64)
                    except Exception as db_err:
                        print(f"[Explorer] Database save screenshot failed: {db_err}")

                    # Discover and click interactive elements
                    log_fn("Explorer", "Exploring navigation links and buttons...")
                    clickable = page.query_selector_all("a[href], button:not([disabled])")
                    visited_hrefs = set(["/"])

                    for el in clickable[:15]:
                        try:
                            href = el.get_attribute("href") or ""
                            tag = el.evaluate("el => el.tagName.toLowerCase()")

                            # Skip external links, anchors, and already visited
                            if href.startswith("http") or href.startswith("#"):
                                continue
                            if href and href in visited_hrefs:
                                continue

                            if tag == "button":
                                el.click(timeout=2000)
                                page.wait_for_timeout(800)
                                log_fn("Explorer", f"Clicked button: {el.inner_text()[:30]}")
                            elif tag == "a" and href:
                                page.goto(f"{base_url}{href}", timeout=8000)
                                pages_visited.append(href)
                                visited_hrefs.add(href)
                                page.wait_for_timeout(500)
                                log_fn("Explorer", f"Visited: {href}")

                        except PlaywrightError:
                            pass  # Element gone / timeout — skip silently
                        except Exception:
                            pass

                except PlaywrightError as e:
                    log_fn("Explorer", f"Page navigation error: {str(e)[:200]}", "warning")
                    console_errors.append({"type": "navigation_error", "text": str(e), "location": base_url})

                browser.close()

        except ImportError:
            log_fn("Explorer", "Playwright not installed. Run: pip install playwright && playwright install chromium", "error")
            console_errors.append({"type": "setup_error", "text": "Playwright not available", "location": ""})

    except Exception as e:
        log_fn("Explorer", f"Explorer error: {str(e)[:300]}", "error")
        console_errors.append({"type": "explorer_error", "text": str(e), "location": ""})

    finally:
        # Always clean up the server process
        if server_proc:
            try:
                if sys.platform != "win32":
                    os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
                else:
                    server_proc.terminate()
                server_proc.wait(timeout=5)
            except Exception:
                pass

    log_fn("Explorer",
           f"Explored {len(pages_visited)} page(s), found {len(console_errors)} error(s), "
           f"{len(network_errors)} network failure(s)")

    return {
        "console_errors": console_errors,
        "network_errors": network_errors,
        "pages_visited": pages_visited,
        "screenshot_b64": screenshot_b64,
        "server_started": True,
    }
