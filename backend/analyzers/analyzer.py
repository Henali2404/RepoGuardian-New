import os
import re
import json
from agents.gemini_client import generate_content_with_fallback

SUPPORTED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cpp", ".c", ".php", ".go",
    ".rb", ".rs", ".cs", ".swift", ".kt", ".m", ".h", ".sh", ".pl", ".pm"
}

IGNORED_DIRS = {
    "node_modules", ".git", "__pycache__", ".next", "dist",
    "build", ".venv", "venv", ".cache", "coverage", ".nyc_output",
    "tmp", "temp", "vendor"
}

IGNORED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".pdf",
    ".lock", ".map", ".min.js", ".min.css", ".zip", ".tar.gz",
    ".woff", ".woff2", ".eot", ".ttf", ".mp4", ".mp3", ".avi",
    ".exe", ".bin", ".db", ".sqlite"
}

# Regex and rules for static checks
STATIC_PATTERNS = [
    {
        "check_id": "SEC-001",
        "category": "Security",
        "subcategory": "hardcoded secrets",
        "title": "Hardcoded Credentials or Secrets",
        "regex": r"(?i)(api_key|apikey|api-key|secret|token|password|passwd|pwd|private_key|aws_access_key_id|aws_secret_access_key|supabase_service_key)\s*=\s*[\"']([^\"']{8,})[\"']",
        "severity": "critical",
        "description": "Possible hardcoded credential or secret key exposed as a string literal.",
        "suggested_fix": "Extract the credential into an environment variable and load it securely.",
        "match_group": 2,  # The group containing the secret to filter false positives
    },
    {
        "check_id": "SEC-002",
        "category": "Security",
        "subcategory": "dangerous eval usage",
        "title": "Dangerous Eval / Exec Usage",
        "regex": r"\b(eval|exec|new Function)\s*\(",
        "severity": "critical",
        "description": "Execution of dynamic code from string input can lead to arbitrary code execution vulnerabilities.",
        "suggested_fix": "Refactor the logic to avoid dynamic code execution using structured parsers or safer abstractions.",
    },
    {
        "check_id": "SEC-003",
        "category": "Security",
        "subcategory": "insecure subprocess usage",
        "title": "Insecure Subprocess Execution",
        "regex": r"\b(subprocess\.(run|Popen|call)|os\.system|os\.popen|child_process\.exec)\s*\([^)]*shell\s*=\s*True",
        "severity": "high",
        "description": "Invoking a subprocess with shell=True can allow shell injection if untrusted inputs are concatenated.",
        "suggested_fix": "Pass arguments as a list and set shell=False, or sanitize inputs thoroughly.",
    },
    {
        "check_id": "SEC-004",
        "category": "Security",
        "subcategory": "SQL injection patterns",
        "title": "Potential SQL Injection",
        "regex": r"(?i)\.(execute|query)\s*\(\s*(f[\"']SELECT|[\"']SELECT[^\"']+((\+[\s\S]+?)|{[\s\S]+?}))",
        "severity": "critical",
        "description": "Raw string interpolation or concatenation in SQL statements can allow attackers to inject arbitrary queries.",
        "suggested_fix": "Use parameterized queries or an Object-Relational Mapper (ORM) to sanitize user input.",
    },
    {
        "check_id": "SEC-005",
        "category": "Security",
        "subcategory": "weak authentication patterns",
        "title": "Weak Hashing / Crypto Usage",
        "regex": r"\b(hashlib\.md5|hashlib\.sha1|crypto\.createHash\s*\(\s*['\"](md5|sha1)['\"])\(",
        "severity": "medium",
        "description": "MD5 and SHA-1 hashing algorithms are cryptographically broken and vulnerable to collision attacks.",
        "suggested_fix": "Use secure algorithms like SHA-256, bcrypt, or Argon2.",
    },
    {
        "check_id": "SEC-006",
        "category": "Security",
        "subcategory": "dangerous CORS configuration",
        "title": "Insecure CORS Wildcard Configuration",
        "regex": r"(?i)(Access-Control-Allow-Origin.*\*|cors\(\s*\{\s*origin\s*:\s*['\"]\*(['\"]))",
        "severity": "medium",
        "description": "Allowing all domains (*) via CORS can expose sensitive API resources if combined with credentials.",
        "suggested_fix": "Specify allowed domains explicitly rather than using a wildcard.",
    },
    {
        "check_id": "CONF-001",
        "category": "Configuration",
        "subcategory": "debug mode",
        "title": "Debug Mode Enabled in Production",
        "regex": r"(?i)(debug\s*=\s*True|DEBUG\s*=\s*True|app.config\['DEBUG'\]\s*=\s*True)",
        "severity": "high",
        "description": "Debug mode prints verbose error traces and might expose administrative consoles, presenting severe security risks in production.",
        "suggested_fix": "Disable debug mode or load it conditionally using env variables.",
    },
    {
        "check_id": "BUG-001",
        "category": "Bugs",
        "subcategory": "unsafe file handling",
        "title": "Potential Path Traversal in File Handling",
        "regex": r"\b(open|readFile|readFileSync|fs\.open)\s*\([^)]*(\+|,|join)[^)]*(req\.query|req\.params|input|path|filename)",
        "severity": "high",
        "description": "Using unsanitized user inputs to build file paths can lead to Arbitrary File Read/Write (Path Traversal).",
        "suggested_fix": "Sanitize paths using library functions (e.g. os.path.basename) or check against a safe directory boundary.",
    }
]

def _read_file_safe(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return ""

class RepositoryScanner:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.files_by_class = {
            "source": [],
            "config": [],
            "dependency": []
        }

    def traverse_and_classify(self) -> dict:
        """Walk the repository and classify files."""
        for root, dirs, files in os.walk(self.repo_path):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                rel_path = os.path.relpath(os.path.join(root, file), self.repo_path)
                
                # Check for ignored extensions
                if ext in IGNORED_EXTENSIONS or any(file.endswith(x) for x in IGNORED_EXTENSIONS):
                    continue

                file_lower = file.lower()
                
                # Dependency files
                if file_lower in ("package.json", "requirements.txt", "pyproject.toml", "gemfile", "cargo.toml", "go.mod"):
                    self.files_by_class["dependency"].append(rel_path)
                # Docker / CI-CD / Configuration
                elif (file_lower in ("dockerfile", "docker-compose.yml", "docker-compose.yaml") or
                      ".github/workflows" in rel_path.replace("\\", "/") or
                      file_lower.startswith(".env")):
                    self.files_by_class["config"].append(rel_path)
                # Source files
                elif ext in SUPPORTED_EXTENSIONS:
                    self.files_by_class["source"].append(rel_path)

        return self.files_by_class

    def run_static_checks(self) -> list[dict]:
        """Perform deterministic checks on files."""
        findings = []
        
        # Scan source files and env configuration files
        target_files = self.files_by_class["source"] + [
            f for f in self.files_by_class["config"] if f.split(os.sep)[-1].startswith(".env")
        ]

        for rel_path in target_files:
            full_path = os.path.join(self.repo_path, rel_path)
            content = _read_file_safe(full_path)
            if not content:
                continue

            lines = content.splitlines()
            for line_idx, line in enumerate(lines, 1):
                # Basic comment stripping to reduce false positives
                stripped_line = line.strip()
                if stripped_line.startswith("#") or stripped_line.startswith("//") or stripped_line.startswith("/*"):
                    continue

                for pattern in STATIC_PATTERNS:
                    match = re.search(pattern["regex"], line)
                    if match:
                        # Extra filter for secrets false positives
                        if pattern["check_id"] == "SEC-001" and "match_group" in pattern:
                            secret_val = match.group(pattern["match_group"]).strip()
                            # Ignore placeholders, standard test templates, or very short values
                            if any(place in secret_val.lower() for place in (
                                "placeholder", "your_key", "example", "your-key", "test-key",
                                "my_secret", "dummy", "postgres://", "mongodb://"
                            )) or len(secret_val) < 8:
                                continue

                        # Capture snippet
                        start = max(0, line_idx - 6)
                        end = min(len(lines), line_idx + 5)
                        snippet = "\n".join(lines[start:end])

                        findings.append({
                            "check_id": pattern["check_id"],
                            "category": pattern["category"],
                            "subcategory": pattern["subcategory"],
                            "title": pattern["title"],
                            "file": rel_path,
                            "line_number": line_idx,
                            "error_type": pattern["subcategory"].replace(" ", "_").capitalize(),
                            "error_description": pattern["description"],
                            "suggested_fix": pattern["suggested_fix"],
                            "code_snippet": snippet,
                            "severity": pattern["severity"],
                            "evidence": f"Found matching pattern in {rel_path} line {line_idx}"
                        })

        return findings

    def verify_with_ai(self, findings: list[dict]) -> list[dict]:
        """Verify findings via targeted LLM prompts to eliminate false positives and expand context."""
        verified_findings = []
        for idx, finding in enumerate(findings):
            # Stop blindly sending the whole codebase. Send only the specific context.
            prompt = f"""You are RepoGuardian Verifier AI.
Verify if the following static analysis warning is a genuine problem in the context of the code snippet.

WARNING DETAILS:
- File: {finding['file']}
- Line: {finding['line_number']}
- Check Title: {finding['title']}
- Code Snippet (centered around target line):
\"\"\"
{finding['code_snippet']}
\"\"\"

Return ONLY a valid JSON object matching this schema (do not output any markdown code blocks, comments or preambles):
{{
  "is_real": true_or_false,
  "confidence_score": 0_to_100,
  "severity_level": "critical_or_high_or_medium_or_low_or_info",
  "explanation": "Clear explanation of the vulnerability and why it is valid",
  "recommended_fix": "Actionable instructions and remediation snippet",
  "estimated_impact": "Impact description if exploited"
}}
"""
            system_instruction = "You are a professional security researcher. You output strictly parseable JSON only."
            try:
                response = generate_content_with_fallback(prompt, system_instruction=system_instruction)
                text = response.text.strip()
                
                # Cleanup potential markdown wrapper
                clean_text = re.sub(r"^```(?:json)?", "", text).replace("```", "").strip()
                parsed = json.loads(clean_text)
                
                if parsed.get("is_real") is True and parsed.get("confidence_score", 0) >= 60:
                    finding["severity"] = parsed.get("severity_level", finding["severity"])
                    finding["error_description"] = parsed.get("explanation", finding["error_description"])
                    finding["suggested_fix"] = parsed.get("recommended_fix", finding["suggested_fix"])
                    finding["estimated_impact"] = parsed.get("estimated_impact", "")
                    finding["confidence"] = parsed.get("confidence_score", 100)
                    verified_findings.append(finding)
                else:
                    print(f"[Scanner] Suppressed false positive: {finding['title']} in {finding['file']}:{finding['line_number']}")
            except Exception as e:
                print(f"[Scanner] AI verification failed for check {finding['check_id']}, fallback to static: {e}")
                # Fallback to deterministic check findings if AI check fails
                finding["confidence"] = 80
                verified_findings.append(finding)
        
        return verified_findings

    def run_checklist_dependency_checks(self) -> list[dict]:
        """Analyze dependencies and configurations against checklist using targeted files."""
        checklist_findings = []
        dep_files = self.files_by_class["dependency"]
        config_files = self.files_by_class["config"]
        
        # Read and bundle content of dependency/config files
        bundles = {}
        for path in dep_files + config_files:
            content = _read_file_safe(os.path.join(self.repo_path, path))
            if content:
                bundles[path] = content[:4000] # truncate to avoid sending huge context

        if not bundles:
            return []

        prompt = f"""You are a configuration and security auditor.
Analyze the following repository config/dependency file contents for problems:

{json.dumps(bundles, indent=2)}

Check specifically for this checklist:
1. SECURITY: Missing security headers, insecure API configuration.
2. PERFORMANCE: Outdated dependency frameworks, heavy bundle sizes.
3. BUGS / QUALITY: Mismatched version pins, deprecated config files.
4. DEPENDENCIES: Packages with known vulnerabilities (e.g., jsonwebtoken < 9.0.0, lodash < 4.17.21, axios < 1.6.0, minimist < 1.2.6).
5. CONFIGURATION: Missing environment configurations, invalid environment structures.
6. ARCHITECTURE: Bad structuring of dependencies, lack of proper package setup.

For each problem found, return a JSON object in a list. Return ONLY a valid JSON list.

Response JSON Schema:
[
  {{
    "category": "Security | Performance | Bugs | Code quality | Dependencies | Configuration | Architecture",
    "title": "Title of the issue",
    "file": "file path",
    "line_number": 1,
    "severity": "critical | warning | info",
    "error_description": "Explanation of the finding",
    "suggested_fix": "How to resolve this issue"
  }}
]
"""
        try:
            response = generate_content_with_fallback(prompt, system_instruction="Output strictly valid JSON lists only.")
            text = response.text.strip()
            clean_text = re.sub(r"^```(?:json)?", "", text).replace("```", "").strip()
            parsed_list = json.loads(clean_text)
            if isinstance(parsed_list, list):
                for item in parsed_list:
                    # Enrich and normalize item
                    item["check_id"] = "CHK-DEP"
                    item["subcategory"] = item.get("category", "Dependencies").lower()
                    item["error_type"] = item.get("category", "Dependencies").replace(" ", "_").capitalize()
                    item["code_snippet"] = ""
                    item["confidence"] = 85
                    checklist_findings.append(item)
        except Exception as e:
            print(f"[Scanner] Checklist scan failed: {e}")
            
        return checklist_findings

    def deduplicate_findings(self, findings: list[dict]) -> list[dict]:
        """Deduplicate findings based on file and line number overlap."""
        deduped = {}
        for f in findings:
            key = (f.get("file"), f.get("line_number"))
            if key not in deduped:
                deduped[key] = f
            else:
                # Merge finding descriptions and titles
                existing = deduped[key]
                existing["title"] = f"{existing['title']} + {f['title']}"
                existing["error_description"] = (
                    f"{existing['error_description']}\n\nEvidence 2: {f['error_description']}"
                )
                existing["suggested_fix"] = (
                    f"{existing['suggested_fix']}\n\nFix 2: {f['suggested_fix']}"
                )
                # Boost severity if multiple patterns hit
                if f["severity"] == "critical" or existing["severity"] == "critical":
                    existing["severity"] = "critical"
                elif f["severity"] == "warning" or existing["severity"] == "warning":
                    existing["severity"] = "warning"
                    
        return list(deduped.values())

def run_advanced_scan(repo_path: str) -> dict:
    scanner = RepositoryScanner(repo_path)
    scanner.traverse_and_classify()
    
    # Static checks
    static_hits = scanner.run_static_checks()
    
    # AI Verify
    verified_hits = scanner.verify_with_ai(static_hits)
    
    # Dependency & configuration checklist checks
    checklist_hits = scanner.run_checklist_dependency_checks()
    
    # Combine & Deduplicate
    all_findings = scanner.deduplicate_findings(verified_hits + checklist_hits)
    
    # Structure results
    bugs = []
    static_issues = []
    security_findings = []
    
    for f in all_findings:
        # Convert severity for Auditor compatibility
        sev = f["severity"].lower()
        if sev not in ("critical", "warning", "info"):
            sev = "warning"
            
        bug_entry = {
            "file": f["file"],
            "line_number": f["line_number"],
            "error_type": f["error_type"],
            "error_description": f["error_description"],
            "suggested_fix": f["suggested_fix"],
            "code_snippet": f.get("code_snippet", ""),
            "severity": sev,
            "issue_id": f.get("check_id", "RG-GEN"),
            "issue_title": f["title"],
            "confidence_score": f.get("confidence", 80),
            "risk_level": "high" if sev == "critical" else "medium" if sev == "warning" else "low",
            "review_verdict": "Approved with Caution" if f.get("confidence", 80) < 90 else "Approved",
            "validity_explanation": f.get("explanation", "Detected via deterministic static scanning."),
            "potential_side_effects": "Remediation changes config or structure and should be checked before merge.",
            "alternative_approaches": "Verify manually in the codebase."
        }
        
        # Add to bugs
        bugs.append(bug_entry)
        
        # Add to static issues (for Architect display)
        static_issues.append({
            "type": f["subcategory"],
            "severity": sev,
            "title": f["title"],
            "description": f["error_description"],
            "suggestion": f["suggested_fix"],
            "file": f["file"],
            "line": f["line_number"]
        })
        
        # Add to security findings (for security report display)
        if f["category"] == "Security":
            security_findings.append({
                "check_id": f.get("check_id"),
                "title": f["title"],
                "file_name": f["file"],
                "line_hint": f["line_number"],
                "severity": sev,
                "description": f["error_description"],
                "fix": f["suggested_fix"],
                "secret_type": f["subcategory"]
            })
            
    # Calculate health score metrics
    criticals = sum(1 for b in bugs if b["severity"] == "critical")
    warnings = sum(1 for b in bugs if b["severity"] == "warning")
    infos = sum(1 for b in bugs if b["severity"] == "info")
    
    score = 100 - (criticals * 15) - (warnings * 5) - (infos * 2)
    score = max(0, score)
    
    scores = {
        "health": score,
        "code_quality": max(0, score - 5),
        "maintainability": max(0, score - 5),
        "documentation": 90,
        "security": max(0, score - 10) if criticals > 0 else score
    }
    
    return {
        "bugs": bugs,
        "static_issues": static_issues,
        "security_findings": security_findings,
        "scores": scores
    }
