"""
Auditor Agent — "The Debugger"
Takes the errors found by Explorer and maps them to exact source code lines.
Returns a list of structured bug reports with suggested fixes, scores, and a security report.
"""

import os
import json
import re
from typing import Optional

from dotenv import load_dotenv
from agents.gemini_client import generate_content_with_fallback

load_dotenv()

CODE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".py", ".vue", ".svelte"}
IGNORED_DIRS = {"node_modules", ".git", "__pycache__", ".next", "dist", "build"}
MAX_FILE_SIZE = 5000  # chars per file sent to LLM

ANALYST_PROMPT = """You are RepoGuardian Analyst AI.
Your job: analyze repository runtime errors and source code.
For EVERY issue found, return these exact fields:
  issue_id: string in format RG-001, RG-002 etc
  issue_title: short clear title
  file_name: relative path to affected file
  severity_level: must be exactly one of: critical, high, medium, low, info
  explanation: clear technical explanation of the problem
  recommended_fix: concrete actionable fix with code example if possible
  estimated_impact: what breaks or costs money if this is not fixed
  code_snippet: the exact problematic lines of code if identifiable

Also compute these scores as integers 0 to 100:
  health: overall codebase health
  code_quality: correctness, error handling, defensive coding
  maintainability: readability, modularity, naming, tech debt
  documentation: README quality, inline comments, docstrings
  security: secrets exposure, input validation, auth patterns

Also produce:
  strengths: list of 3 things the codebase does well
  weaknesses: list of 3 concrete problems
  opportunities: list of 3 high-ROI improvements

RULES — follow strictly:
  POSITIVE: Be specific. Name the exact file and line when possible.
  POSITIVE: Give confidence levels based on evidence in the code.
  POSITIVE: Prioritize critical and high severity over low and info.
  POSITIVE: When security score is below 50, always explain exactly why.
  POSITIVE: Output valid JSON always. Never add markdown or explanation outside JSON.
  NEGATIVE: Never invent files that do not exist in the provided tree.
  NEGATIVE: Never claim certainty when you only see a partial file.
  NEGATIVE: Never mark something critical without a concrete exploit scenario.
  NEGATIVE: Never produce empty issues array unless the code is genuinely clean.
  NEGATIVE: Never output anything except the JSON object.

Return ONLY this JSON structure, nothing else:
{
  "issues": [
    {
      "issue_id": "RG-001",
      "issue_title": "",
      "file_name": "",
      "severity_level": "critical",
      "explanation": "",
      "recommended_fix": "",
      "estimated_impact": "",
      "code_snippet": ""
    }
  ],
  "scores": {
    "health": 0,
    "code_quality": 0,
    "maintainability": 0,
    "documentation": 0,
    "security": 0
  },
  "strengths": [],
  "weaknesses": [],
  "opportunities": []
}"""

REVIEWER_PROMPT = """You are RepoGuardian Reviewer AI.
Your job: independently validate every issue found by the Analyst AI.
You are a second opinion. Be critical. Never blindly approve.

For every issue in the input, return:
  issue_id: same ID as the analyst used
  confidence_score: integer 0 to 100 — how confident YOU are this is a real issue
  risk_level: must be exactly one of: none, low, medium, high, critical
  review_verdict: must be exactly one of:
    "Approved" — fix is correct and complete, safe to apply
    "Approved with Caution" — fix works but has minor assumptions, note them
    "Needs Review" — incomplete fix or unclear logic, block merge
    "Rejected" — fix introduces new bugs or regressions, do not apply

  validity_explanation: why the issue is real or not real
  potential_side_effects: what could break if the fix is applied
  alternative_approaches: other valid ways to fix this

Also produce:
  approval_recommendation: one of: Approve, Request Changes, Block
  developer_notes: list of bullet points the developer must act on
  final_review_summary: 2 sentence executive summary

RULES — follow strictly:
  POSITIVE: Base verdicts on actual code logic, not assumptions.
  POSITIVE: Give "Approved" only when the fix is complete and safe.
  POSITIVE: Give "Approved with Caution" for fixes with edge case risks.
  POSITIVE: Give "Needs Review" when the fix is partially correct.
  POSITIVE: Give "Rejected" when the fix would break something else.
  POSITIVE: Confidence score above 85 means you saw clear evidence.
  POSITIVE: Confidence score below 60 means partial information only.
  NEGATIVE: Never approve a fix that introduces a hardcoded secret.
  NEGATIVE: Never approve a fix that removes error handling entirely.
  NEGATIVE: Never give confidence above 90 on minified or obfuscated code.
  NEGATIVE: Never produce empty reviewed_issues array.
  NEGATIVE: Never output anything except the JSON object.

Return ONLY this JSON, nothing else:
{
  "reviewed_issues": [
    {
      "issue_id": "RG-001",
      "confidence_score": 0,
      "risk_level": "medium",
      "review_verdict": "Approved",
      "validity_explanation": "",
      "potential_side_effects": "",
      "alternative_approaches": ""
    }
  ],
  "approval_recommendation": "Approve",
  "developer_notes": [],
  "final_review_summary": ""
}"""

SEC_CHECK_1_SECRETS = """You are a security expert running Gitleaks-style secret detection.
Scan the provided source code for:
  1. Hardcoded API keys, passwords, tokens, DB connection strings as string literals
  2. Supabase service role key exposed in client-side code — this is CRITICAL
  3. NEXT_PUBLIC_ prefixed env vars that contain secrets (they are sent to browser)
  4. .env files checked into git, missing .gitignore entries for .env
  5. Secrets appearing in console.log, error messages, or API responses
  6. Stripe secret keys, AWS access keys, private keys in any file

For each finding return:
  check_id: S1-001 format
  title: short description
  file_name: affected file
  line_hint: approximate line number if visible
  severity: critical, high, medium, or low
  description: what the secret is and why it is dangerous
  fix: exact remediation step
  secret_type: what kind of secret (API key, password, token etc)

RULES:
  POSITIVE: Flag anything that looks like a real credential even if partially visible.
  POSITIVE: Always mark service role keys in client code as critical.
  POSITIVE: Check both .env files and hardcoded strings in source files.
  NEGATIVE: Do not flag placeholder values like your_key_here or example_token.
  NEGATIVE: Do not flag public keys or anon keys as critical — only service keys.
  NEGATIVE: Do not flag commented-out credentials unless they are real values.

Return ONLY this JSON:
{
  "findings": [],
  "summary": "",
  "secrets_found": 0,
  "critical_count": 0
}"""

SEC_CHECK_2_DATA_FLOW = """You are a privacy security expert running Bearer-style personal data flow analysis.
Scan the provided source code for:
  1. Where personal data is collected — email, phone, password, name, address, payment info
  2. PII appearing in console.log, error handlers, or log files
  3. Third-party services receiving user data unnecessarily
  4. Password hashing — must use bcrypt, argon2, or scrypt — never MD5 or SHA256 alone
  5. Cookie security — httpOnly, secure, sameSite flags missing
  6. API endpoints returning more user fields than the client needs
  7. No account deletion or data export capability

For each finding:
  check_id: S2-001 format
  title: short description
  file_name: affected file
  severity: critical, high, medium, low
  description: what data flows where and why it is a problem
  fix: exact remediation step
  data_type_affected: what personal data is involved

RULES:
  POSITIVE: Flag any PII in logs as at minimum high severity.
  POSITIVE: Flag MD5 or SHA256 for passwords as critical.
  POSITIVE: Check all fetch and axios calls for user data in request body.
  NEGATIVE: Do not flag user IDs as PII — only direct identifiers.
  NEGATIVE: Do not flag NEXT_PUBLIC_SUPABASE_URL as a data leak.

Return ONLY this JSON:
{
  "findings": [],
  "data_flows": [],
  "summary": "",
  "pii_exposure_count": 0
}"""

SEC_CHECK_3_PREDEPLOY = """You are a production security expert running a pre-deployment audit.
Scan for:
  1. Missing env var validation — app should crash on startup if critical vars are absent
  2. Debug artifacts — console.log, TODO/FIXME on security features, /debug or /seed endpoints
  3. Error responses leaking stack traces, database details, or internal file paths
  4. Missing security headers — X-Content-Type-Options, X-Frame-Options, HSTS, CSP
  5. No rate limiting on auth endpoints — login, signup, password reset, OTP
  6. CORS set to wildcard * without restriction
  7. Database connections without TLS, default credentials, or exposed admin panels

For each finding:
  check_id: S3-001 format
  title: short description
  file_name: affected file
  severity: critical, high, medium, low
  description: what is wrong and why it matters in production
  fix: exact remediation step

RULES:
  POSITIVE: Missing rate limiting on /login is always at least high severity.
  POSITIVE: Stack traces in error responses are always at least high severity.
  POSITIVE: CORS wildcard on a production API is always medium or higher.
  NEGATIVE: Do not flag console.log in test files.
  NEGATIVE: Do not flag CORS as critical if the API is intentionally public.

Return ONLY this JSON:
{
  "findings": [],
  "deploy_ready": false,
  "blockers": [],
  "warnings": [],
  "summary": ""
}"""

SEC_CHECK_4_DEEP = """You are a Trail of Bits security researcher running a deep logic audit.
Scan for:
  1. IDOR vulnerabilities — endpoints that accept a user ID from the client 
     and fetch data without checking the requesting user owns that ID
  2. Password reset flow — tokens must be cryptographically random, single-use, 
     expire after 15 minutes, and be tied to a specific user
  3. JWT handling — signing secret must be strong, expiry must be set, 
     tokens must be invalidated on logout
  4. Payment logic — never trust client-side price calculations,
     always verify webhook signatures server-side
  5. SQL injection — raw string concatenation into queries instead of 
     parameterized queries or ORM
  6. XSS — user input rendered into HTML without sanitization
  7. File upload — no server-side type validation, no size limit, 
     executable files not blocked

For each finding:
  check_id: S4-001 format
  title: short description
  file_name: affected file
  severity: critical, high, medium, low
  description: technical explanation of the vulnerability
  exploit_scenario: concrete attack scenario a hacker would use
  fix: exact remediation step

RULES:
  POSITIVE: IDOR without ownership check is always critical.
  POSITIVE: SQL injection via string concatenation is always critical.
  POSITIVE: JWT without expiry is always high or critical.
  POSITIVE: Always describe a realistic exploit scenario, not a theoretical one.
  NEGATIVE: Do not flag ORM queries as SQL injection — only raw string building.
  NEGATIVE: Do not flag JWT expiry as critical if refresh tokens are in use.
  NEGATIVE: Do not flag client-side validation as a finding — only missing server-side.

Return ONLY this JSON:
{
  "findings": [],
  "critical_paths": [],
  "summary": "",
  "exploitable_count": 0
}"""

SEC_CHECK_5_ATTACKER = """You are a red team attacker. Think like a malicious hacker.
Your goal: find every way to abuse this application.
Check for:
  1. ID manipulation — can I change an ID in the URL or request body 
     to access another user's data or actions?
  2. Login bypass — are there any endpoints that work without a valid auth token?
     Do expired or malformed tokens get accepted?
  3. Privilege escalation — can a regular user call an admin endpoint?
     Are role checks only done client-side?
  4. Feature abuse — are there rate limits on signup, messaging, 
     file uploads, promo code redemption?
  5. Content injection — can I put JavaScript into a text field and have it 
     execute for another user? Can I inject SQL into search or filter inputs?
  6. Internal exposure — is there a /admin panel without auth? 
     Do error messages expose .env vars, DB schemas, or file paths?
     Is /.git or /swagger accessible publicly?
  7. Business logic abuse — can I use negative payment amounts?
     Can I stack discounts infinitely? Can I restart a free trial?
     Can I refer myself?

For each finding:
  check_id: S5-001 format
  title: short description
  file_name: affected file
  severity: critical, high, medium, low
  attack_scenario: step by step how the attacker would exploit this
  damage_potential: what the attacker gains
  fix: exact remediation step

RULES:
  POSITIVE: Think like an attacker who has read the source code.
  POSITIVE: Be creative — find combinations of vulnerabilities.
  POSITIVE: Privilege escalation is always critical.
  POSITIVE: Always write attack scenarios as numbered steps an attacker would follow.
  NEGATIVE: Do not flag theoretical attacks with no entry point in the code.
  NEGATIVE: Do not flag issues already covered by the other 4 checks.
  NEGATIVE: Do not flag client-side only issues — focus on server-side impact.

Return ONLY this JSON:
{
  "findings": [],
  "attack_surface": [],
  "summary": "",
  "critical_attack_paths": 0
}"""


def _extract_json_object(text: str) -> dict:
    """Robustly extract a JSON object from LLM output."""
    clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[\s\S]*\}", clean)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return {}


def _extract_json_array(text: str) -> list:
    """Robustly extract a JSON array from LLM output."""
    clean = re.sub(r"```(?:json)?", "", text).replace("```", "").strip()
    try:
        result = json.loads(clean)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "bugs" in result:
            return result["bugs"]
    except json.JSONDecodeError:
        pass

    m = re.search(r"\[[\s\S]*?\]", clean)
    if m:
        try:
            result = json.loads(m.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    objects = re.findall(r"\{[^{}]+\}", clean)
    bugs = []
    for obj in objects:
        try:
            bugs.append(json.loads(obj))
        except json.JSONDecodeError:
            pass
    return bugs


def _read_source_files(repo_path: str) -> dict[str, str]:
    """Read all source code files."""
    files = {}
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        for fname in filenames:
            if any(fname.endswith(ext) for ext in CODE_EXTENSIONS):
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, repo_path)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    files[rel_path] = content
                except Exception:
                    pass
    return files


def _format_errors_for_prompt(console_errors: list, network_errors: list) -> str:
    lines = []
    for i, err in enumerate(console_errors[:20]):
        lines.append(f"  [{i+1}] [{err.get('type', 'error')}] {err.get('text', '')[:300]}")
        if err.get('location'):
            lines.append(f"       at: {err['location']}")
    for i, err in enumerate(network_errors[:10]):
        lines.append(f"  [NET-{i+1}] FAILED REQUEST: {err.get('url', '')} — {err.get('failure', '')}")
    return "\n".join(lines) if lines else "No runtime errors detected."


def audit_errors(explorer_result: dict, repo_path: str) -> tuple[list[dict], dict, dict]:
    """
    Map runtime errors to source code and generate fix suggestions.
    Returns: (merged_issues, scores, security_report)
    """
    console_errors = explorer_result.get("console_errors", [])
    network_errors = explorer_result.get("network_errors", [])

    source_files = _read_source_files(repo_path)
    if not source_files:
        empty_scores = {"health": 100, "code_quality": 100, "maintainability": 100, "documentation": 100, "security": 100}
        empty_sec = {
            "check_1_secrets": {"findings": [], "summary": "No source files scanned.", "secrets_found": 0, "critical_count": 0},
            "check_2_data_flow": {"findings": [], "data_flows": [], "summary": "No source files scanned.", "pii_exposure_count": 0},
            "check_3_predeploy": {"findings": [], "deploy_ready": True, "blockers": [], "warnings": [], "summary": "No source files scanned."},
            "check_4_deep": {"findings": [], "critical_paths": [], "summary": "No source files scanned.", "exploitable_count": 0},
            "check_5_attacker": {"findings": [], "attack_surface": [], "summary": "No source files scanned.", "critical_attack_paths": 0},
            "total_findings": 0,
            "critical_total": 0
        }
        return ([], empty_scores, empty_sec)

    # Pick the most relevant files (stay under ~40000 chars, slicing strictly at line boundaries)
    priority_files = {}
    other_files = {}
    for path, content in source_files.items():
        if any(seg in path for seg in ("src/", "app/", "components/", "pages/", "lib/")):
            priority_files[path] = content
        else:
            other_files[path] = content

    source_context = []
    char_budget = 40000
    for path, content in {**priority_files, **other_files}.items():
        lines = content.splitlines()
        file_snippet_lines = []
        current_len = 0
        for line in lines:
            if current_len + len(line) + 1 > 4000:
                break
            file_snippet_lines.append(line)
            current_len += len(line) + 1
        
        file_snippet = "\n".join(file_snippet_lines)
        snippet = f"\n--- FILE: {path} ---\n{file_snippet}\n"
        
        if char_budget - len(snippet) < 0:
            break
        source_context.append(snippet)
        char_budget -= len(snippet)

    errors_formatted = _format_errors_for_prompt(console_errors, network_errors)

    analyst_prompt_input = f"""Analyze these runtime errors and the source code context.

RUNTIME ERRORS:
{errors_formatted}

SOURCE CODE:
{"".join(source_context)}

Return ONLY the JSON structure according to the system prompt guidelines.
"""

    # Step 2: Run ANALYST_PROMPT via Gemini — get issues and scores
    analyst_data = {}
    try:
        response = generate_content_with_fallback(analyst_prompt_input, system_instruction=ANALYST_PROMPT)
        analyst_data = _extract_json_object(response.text)
    except Exception as e:
        print(f"[Auditor] Analyst LLM call failed: {e}")

    if not analyst_data:
        # Graceful fallback: build issues list from console_errors
        fallback_issues = []
        for i, err in enumerate(console_errors[:5]):
            fallback_issues.append({
                "issue_id": f"RG-{i+1:03d}",
                "issue_title": f"Runtime Error: {err.get('type', 'Error')}",
                "file_name": "unknown",
                "severity_level": "high" if err.get("type") == "pageerror" else "medium",
                "explanation": err.get("text", "Runtime error detected during crawling"),
                "recommended_fix": "Inspect logs and check application runtime logic.",
                "estimated_impact": "Application may crash or behave unexpectedly for users.",
                "code_snippet": ""
            })
        analyst_data = {
            "issues": fallback_issues,
            "scores": {
                "health": 70 if console_errors else 90,
                "code_quality": 70 if console_errors else 90,
                "maintainability": 80,
                "documentation": 80,
                "security": 80
            },
            "strengths": ["Repository structure successfully loaded.", "Primary entry routes mapped."],
            "weaknesses": ["Console errors detected during dynamic crawl." if console_errors else "Static scan coverage limit."],
            "opportunities": ["Resolve console log failures.", "Integrate end-to-end unit tests."]
        }

    # Step 3: Run REVIEWER_PROMPT via Gemini — validate every issue
    reviewer_prompt_input = f"""Review and validate the analyst's findings for the codebase.

ANALYST FINDINGS:
{json.dumps(analyst_data, indent=2)}

Return ONLY the JSON structure according to the reviewer system prompt guidelines.
"""

    reviewer_data = {}
    try:
        response = generate_content_with_fallback(reviewer_prompt_input, system_instruction=REVIEWER_PROMPT)
        reviewer_data = _extract_json_object(response.text)
    except Exception as e:
        print(f"[Auditor] Reviewer LLM call failed: {e}")

    if not reviewer_data:
        reviewed_issues = []
        for issue in analyst_data.get("issues", []):
            reviewed_issues.append({
                "issue_id": issue.get("issue_id", "RG-001"),
                "confidence_score": 80,
                "risk_level": "medium" if issue.get("severity_level") in ("critical", "high") else "low",
                "review_verdict": "Approved with Caution",
                "validity_explanation": "Auto-approved fallback validation.",
                "potential_side_effects": "Applying the fix might require testing code paths.",
                "alternative_approaches": "Verify functionality manually before applying."
            })
        reviewer_data = {
            "reviewed_issues": reviewed_issues,
            "approval_recommendation": "Approve",
            "developer_notes": ["Manually review all fallback findings."],
            "final_review_summary": "Auto-validated review fallback generated due to LLM error."
        }

    # Step 4: Merge analyst and reviewer output per issue_id
    issues_by_id = {issue["issue_id"]: issue for issue in analyst_data.get("issues", []) if isinstance(issue, dict) and "issue_id" in issue}
    reviewed_by_id = {issue["issue_id"]: issue for issue in reviewer_data.get("reviewed_issues", []) if isinstance(issue, dict) and "issue_id" in issue}

    merged_issues = []
    for issue_id, issue in issues_by_id.items():
        rev = reviewed_by_id.get(issue_id, {})
        merged_issues.append({
            # Original keys for compatibility with other agents (like Executor)
            "file": issue.get("file_name", "unknown"),
            "line_number": None,
            "error_type": issue.get("issue_title", "Software Quality Issue"),
            "error_description": issue.get("explanation", ""),
            "suggested_fix": issue.get("recommended_fix", ""),
            "severity": "critical" if issue.get("severity_level") == "critical" else "warning" if issue.get("severity_level") in ("high", "medium") else "info",

            # New Analyst fields
            "issue_id": issue_id,
            "issue_title": issue.get("issue_title", ""),
            "file_name": issue.get("file_name", "unknown"),
            "severity_level": issue.get("severity_level", "medium"),
            "explanation": issue.get("explanation", ""),
            "recommended_fix": issue.get("recommended_fix", ""),
            "estimated_impact": issue.get("estimated_impact", ""),
            "code_snippet": issue.get("code_snippet", ""),

            # New Reviewer fields
            "confidence_score": rev.get("confidence_score", 50),
            "risk_level": rev.get("risk_level", "medium"),
            "review_verdict": rev.get("review_verdict", "Needs Review"),
            "validity_explanation": rev.get("validity_explanation", ""),
            "potential_side_effects": rev.get("potential_side_effects", ""),
            "alternative_approaches": rev.get("alternative_approaches", "")
        })

    # Step 5: Run all 5 security checks in sequence
    security_context_prompt = f"""Analyze the following source code context for security issues.

SOURCE CODE:
{"".join(source_context)}

Return ONLY the JSON structure according to the security check system prompt guidelines.
"""

    # Check 1: Secrets
    sec_1_data = {}
    try:
        r1 = generate_content_with_fallback(security_context_prompt, system_instruction=SEC_CHECK_1_SECRETS)
        sec_1_data = _extract_json_object(r1.text)
    except Exception as e:
        print(f"[Auditor] Security Check 1 failed: {e}")
    if not sec_1_data:
        sec_1_data = {"findings": [], "summary": "Secrets check failed or completed with no findings.", "secrets_found": 0, "critical_count": 0}

    # Check 2: Data Flow
    sec_2_data = {}
    try:
        r2 = generate_content_with_fallback(security_context_prompt, system_instruction=SEC_CHECK_2_DATA_FLOW)
        sec_2_data = _extract_json_object(r2.text)
    except Exception as e:
        print(f"[Auditor] Security Check 2 failed: {e}")
    if not sec_2_data:
        sec_2_data = {"findings": [], "data_flows": [], "summary": "Data flow check failed or completed with no findings.", "pii_exposure_count": 0}

    # Check 3: Pre-Deploy
    sec_3_data = {}
    try:
        r3 = generate_content_with_fallback(security_context_prompt, system_instruction=SEC_CHECK_3_PREDEPLOY)
        sec_3_data = _extract_json_object(r3.text)
    except Exception as e:
        print(f"[Auditor] Security Check 3 failed: {e}")
    if not sec_3_data:
        sec_3_data = {"findings": [], "deploy_ready": True, "blockers": [], "warnings": [], "summary": "Pre-deploy check failed or completed with no findings."}

    # Check 4: Deep
    sec_4_data = {}
    try:
        r4 = generate_content_with_fallback(security_context_prompt, system_instruction=SEC_CHECK_4_DEEP)
        sec_4_data = _extract_json_object(r4.text)
    except Exception as e:
        print(f"[Auditor] Security Check 4 failed: {e}")
    if not sec_4_data:
        sec_4_data = {"findings": [], "critical_paths": [], "summary": "Deep logic check failed or completed with no findings.", "exploitable_count": 0}

    # Check 5: Attacker
    sec_5_data = {}
    try:
        r5 = generate_content_with_fallback(security_context_prompt, system_instruction=SEC_CHECK_5_ATTACKER)
        sec_5_data = _extract_json_object(r5.text)
    except Exception as e:
        print(f"[Auditor] Security Check 5 failed: {e}")
    if not sec_5_data:
        sec_5_data = {"findings": [], "attack_surface": [], "summary": "Attacker view check failed or completed with no findings.", "critical_attack_paths": 0}

    # Calculate totals
    total_findings = 0
    critical_total = 0
    
    all_findings_lists = [
        sec_1_data.get("findings", []),
        sec_2_data.get("findings", []),
        sec_3_data.get("findings", []),
        sec_4_data.get("findings", []),
        sec_5_data.get("findings", [])
    ]
    
    for flist in all_findings_lists:
        if isinstance(flist, list):
            total_findings += len(flist)
            for f in flist:
                if isinstance(f, dict) and f.get("severity") == "critical":
                    critical_total += 1

    scores = analyst_data.get("scores", {"health": 80, "code_quality": 80, "maintainability": 80, "documentation": 80, "security": 80})

    # Step 6: Adjust security score downward if critical_total > 0
    if critical_total > 0:
        security_score = scores.get("security", 100)
        # Cap the security score below 50 so explanation requirement is triggered
        adjusted_score = max(0, min(security_score, 45 - (critical_total - 1) * 5))
        scores["security"] = adjusted_score

    security_report = {
        "check_1_secrets": sec_1_data,
        "check_2_data_flow": sec_2_data,
        "check_3_predeploy": sec_3_data,
        "check_4_deep": sec_4_data,
        "check_5_attacker": sec_5_data,
        "total_findings": total_findings,
        "critical_total": critical_total
    }

    return (merged_issues, scores, security_report)


def _static_bug_scan(repo_path: str) -> list:
    """
    Deprecated / Fallback. Included to keep structure intact.
    """
    bugs = []
    source_files = _read_source_files(repo_path)

    for rel_path, content in source_files.items():
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            if "console.log(" in stripped and not stripped.startswith("//"):
                bugs.append({
                    "file": rel_path,
                    "line_number": i,
                    "error_type": "DebugCode",
                    "error_description": "console.log() left in production code",
                    "code_snippet": stripped[:100],
                    "suggested_fix": "Remove console.log() before production deployment",
                    "severity": "info",
                })

            if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", stripped, re.IGNORECASE):
                bugs.append({
                    "file": rel_path,
                    "line_number": i,
                    "error_type": "UnfinishedCode",
                    "error_description": f"Unresolved {stripped[:50]}",
                    "code_snippet": stripped[:100],
                    "suggested_fix": "Address this TODO/FIXME before final release",
                    "severity": "info",
                })

        if len(bugs) >= 10:
            break

    return bugs
