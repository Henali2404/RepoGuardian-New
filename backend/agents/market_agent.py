"""
Market Agent — "The Strategist"
Given a GitHub repository's source code, README, and project description,
produces a complete market intelligence report.
"""

import os
import json
import re
from agents.gemini_client import generate_content_with_fallback

MARKET_AGENT_PROMPT = """You are a senior startup strategist and market analyst.
Given a GitHub repository's source code, README, and project description,
produce a complete market intelligence report.

You must return these exact fields:

  project_summary: 2 sentence plain English description of what this project does
  one_line_pitch: one powerful investor-style pitch sentence under 15 words
  viability_score: integer 0 to 100 rating business potential
  viability_reason: 2 sentence explanation of the score

  market_exists: boolean — does a paying market exist for this?
  market_size: string like "$4.5B developer tools market"

  target_audience: array of objects, each with:
    segment: who they are
    pain_point: what problem they have that this solves
    size: rough worldwide count

  competitors: array of objects, each with:
    name: competitor name
    what_they_do: one sentence
    your_advantage: what this project does that they do not
    their_weakness: what they cannot do
    pricing: their price if known

  market_gap: paragraph explaining what unique gap this project fills

  unique_differentiators: list of 3 to 5 specific technical advantages

  startup_roadmap: array of steps, each with:
    step: integer starting at 1
    phase: Validate, MVP, Launch, Monetize, or Scale
    action: specific concrete action to take
    timeline: e.g. Week 1-2 or Month 3
    metric: measurable success indicator for this step

  risks: array of objects, each with:
    risk: what could go wrong
    mitigation: how to reduce that risk

  recommended_next_feature: single most valuable feature to build next
  investor_appeal: one sentence on why investors would or would not fund this

RULES — follow strictly:
  POSITIVE: Be honest. If competitors dominate, say so clearly.
  POSITIVE: Give a low viability score if the market is too crowded.
  POSITIVE: Make startup_roadmap steps specific and achievable.
  POSITIVE: Name real competitors by their actual product name.
  POSITIVE: Base market_size on real industry data when possible.
  POSITIVE: unique_differentiators must be technical facts, not marketing claims.
  NEGATIVE: Do not claim the project is unique if it is not.
  NEGATIVE: Do not inflate the viability_score to seem encouraging.
  NEGATIVE: Do not invent competitors that do not exist.
  NEGATIVE: Do not give generic advice like "talk to customers" without specifics.
  NEGATIVE: Never output anything except the JSON object.

Return ONLY this JSON structure, nothing else:
{
  "project_summary": "",
  "one_line_pitch": "",
  "viability_score": 0,
  "viability_reason": "",
  "market_exists": true,
  "market_size": "",
  "target_audience": [],
  "competitors": [],
  "market_gap": "",
  "unique_differentiators": [],
  "startup_roadmap": [],
  "risks": [],
  "recommended_next_feature": "",
  "investor_appeal": ""
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


def analyze_market(repo_path: str, scan_result: dict) -> dict:
    """Analyze market potential and competitive landscape of the repository."""
    readme_content = ""
    readme_path = os.path.join(repo_path, "README.md")
    if os.path.exists(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8", errors="ignore") as f:
                readme_content = f.read(3000)
        except Exception:
            pass

    pkg_description = ""
    pkg_keywords = []
    pkg_path = os.path.join(repo_path, "package.json")
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8", errors="ignore") as f:
                pkg_data = json.load(f)
                pkg_description = pkg_data.get("description", "")
                pkg_keywords = pkg_data.get("keywords", [])
        except Exception:
            pass

    framework = scan_result.get("framework", "unknown")
    description = scan_result.get("description", "")
    file_tree = scan_result.get("file_tree", [])

    prompt = f"""Generate a market intelligence report for the codebase with this information:

FRAMEWORK: {framework}
PROJECT DESCRIPTION (from scan): {description}
PACKAGE.JSON DESCRIPTION: {pkg_description}
PACKAGE.JSON KEYWORDS: {pkg_keywords}
FILE TREE: {file_tree}

README CONTENT (TRUNCATED):
{readme_content}

Return ONLY the JSON structure according to the system prompt guidelines.
"""

    response_data = {}
    try:
        response = generate_content_with_fallback(prompt, system_instruction=MARKET_AGENT_PROMPT)
        response_data = _extract_json_object(response.text)
    except Exception as e:
        print(f"[Market Agent] LLM call failed: {e}")

    if not response_data:
        response_data = {
            "project_summary": f"A software application built using the {framework} stack.",
            "one_line_pitch": "Automated codebase ready for development and scale.",
            "viability_score": 50,
            "viability_reason": "Fallback data generated. Viability is moderate based on file structure.",
            "market_exists": True,
            "market_size": "Unknown Developer Tools market",
            "target_audience": [
                {"segment": "Developers", "pain_point": "Inefficient development workflows", "size": "30M"}
            ],
            "competitors": [
                {"name": "Standard Alternatives", "what_they_do": "Generic tools", "your_advantage": "Autonomous AI insights", "their_weakness": "Requires manual setup", "pricing": "Varies"}
            ],
            "market_gap": "Provides structured developer-centric workflows with automated code generation.",
            "unique_differentiators": ["Framework integration", "Multi-agent structure"],
            "startup_roadmap": [
                {"step": 1, "phase": "Validate", "action": "Validate with early adopters", "timeline": "Week 1-2", "metric": "Interviews completed"},
                {"step": 2, "phase": "MVP", "action": "Launch MVP to pilot group", "timeline": "Week 3-4", "metric": "Active user feedback"}
            ],
            "risks": [
                {"risk": "Market competition", "mitigation": "Target specific framework niches"}
            ],
            "recommended_next_feature": "Integration with CI/CD deployment pipelines",
            "investor_appeal": "High appeal due to developer tool trends and automated workflows."
        }

    return response_data
