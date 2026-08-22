/**
 * Centralized API client.
 * All backend calls go through here so we only change the URL in one place.
 */

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

import { supabase, getAccessToken, type JobRow } from "./supabase";

async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export interface LogEntry {
  agent: string;
  message: string;
  level: "info" | "warning" | "error" | "success";
}

export interface Bug {
  file: string;
  line_number: number | null;
  error_type: string;
  error_description: string;
  code_snippet: string;
  suggested_fix: string;
  severity: "critical" | "warning" | "info";
}

export interface ArchitectureIssue {
  type: string;
  severity: "critical" | "warning" | "info";
  title: string;
  description: string;
  suggestion: string;
  file: string | null;
  line?: number | null;
}

export interface Diff {
  file: string;
  original: string;
  fixed: string;
  bug: Bug;
  success: boolean;
  error: string | null;
}

export interface Scores {
  health: number | null
  code_quality: number | null
  maintainability: number | null
  documentation: number | null
  security: number | null
}

export interface IssueItem {
  // Analyst fields
  issue_id: string
  issue_title: string
  file_name: string
  line_number?: number | null
  severity_level: "critical" | "high" | "medium" | "low" | "info"
  explanation: string
  recommended_fix: string
  estimated_impact: string
  code_snippet?: string
  // Reviewer fields
  confidence_score: number | null
  risk_level: "none" | "low" | "medium" | "high" | "critical" | null
  review_verdict: "Approved" | "Approved with Caution" | "Needs Review" | "Rejected" | null
  validity_explanation: string
  potential_side_effects: string
  alternative_approaches: string
}

export interface SecurityFinding {
  check_id: string
  title: string
  file_name?: string
  severity: "critical" | "high" | "medium" | "low"
  description: string
  fix: string
  attack_scenario?: string
  exploit_scenario?: string
  damage_potential?: string
}

export interface SecurityReport {
  check_1_secrets: { findings: SecurityFinding[]; summary: string; secrets_found: number; critical_count: number }
  check_2_data_flow: { findings: SecurityFinding[]; summary: string; pii_exposure_count: number }
  check_3_predeploy: { findings: SecurityFinding[]; summary: string; deploy_ready: boolean; blockers: string[] }
  check_4_deep: { findings: SecurityFinding[]; summary: string; exploitable_count: number }
  check_5_attacker: { findings: SecurityFinding[]; summary: string; critical_attack_paths: number }
  total_findings: number
  critical_total: number
}

export interface MarketReport {
  project_summary: string
  one_line_pitch: string
  viability_score: number
  viability_reason: string
  market_exists: boolean
  market_size: string
  target_audience: { segment: string; pain_point: string; size: string }[]
  competitors: { name: string; what_they_do: string; your_advantage: string; their_weakness: string; pricing: string }[]
  market_gap: string
  unique_differentiators: string[]
  startup_roadmap: { step: number; phase: string; action: string; timeline: string; metric: string }[]
  risks: { risk: string; mitigation: string }[]
  recommended_next_feature: string
  investor_appeal: string
}

export interface JobResult {
  repo_url: string;
  scan: {
    framework: string;
    description: string;
    has_tests: boolean;
    dockerfile_exists: boolean;
    env_file_exists: boolean;
    file_tree: string[];
  };
  explorer?: {
    console_errors: any[];
    network_errors: any[];
    pages_visited: string[];
    screenshot_b64: string | null;
    server_started: boolean;
  };
  bugs: Bug[];
  architecture?: {
    static_issues: ArchitectureIssue[];
    ai_analysis: string;
    summary?: { critical?: number; warnings?: number; info?: number; metrics?: { complexity?: number; maintainability?: number } };
    score?: number;
  };
  diffs: Diff[];
  scores?: Scores | null;
  security_report?: SecurityReport | null;
  market_report?: MarketReport | null;
  screenshot_b64?: string | null;
}

export interface JobStatus {
  status: "running" | "done" | "stopped" | "error";
  new_logs: LogEntry[];
  all_logs: LogEntry[];
  result: JobResult | null;
  error: string | null;
  scores?: Scores | null;
  security_report?: SecurityReport | null;
  market_report?: MarketReport | null;
  screenshot_b64?: string | null;
  approval_status?: string;
  push_status?: string;
  pr_url?: string | null;
}

function parseJsonValue<T>(value: T): T {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as T;
  } catch {
    return value;
  }
}

export function normalizeJobResult(rawResult: unknown): JobResult | null {
  rawResult = parseJsonValue(rawResult);
  if (!rawResult || typeof rawResult !== "object") return null;
  const raw = rawResult as Record<string, any>;
  const rawArchitecture = parseJsonValue(raw.architecture ?? raw.architecture_analysis ?? raw.architecture_report);
  const architecture = Array.isArray(rawArchitecture)
    ? { static_issues: rawArchitecture, ai_analysis: "" }
    : rawArchitecture;
  const marketReport = parseJsonValue(raw.market_report ?? raw.market);
  const normalized: JobResult = {
    ...raw,
    bugs: Array.isArray(raw.bugs) ? raw.bugs : Array.isArray(raw.issues) ? raw.issues : [],
    diffs: Array.isArray(raw.diffs) ? raw.diffs : Array.isArray(raw.fixes) ? raw.fixes : [],
    architecture: architecture && typeof architecture === "object" ? architecture : undefined,
    market_report: marketReport && typeof marketReport === "object" ? marketReport : null,
    security_report: parseJsonValue(raw.security_report),
  } as JobResult;
  console.debug("[analysis] normalized result", {
    keys: Object.keys(raw),
    bugs: normalized.bugs.length,
    diffs: normalized.diffs.length,
    architectureIssues: normalized.architecture?.static_issues?.length ?? 0,
    market: Boolean(normalized.market_report),
  });
  return normalized;
}

export function normalizeJobStatus(rawStatus: JobStatus & { result?: unknown }): JobStatus {
  const result = normalizeJobResult(rawStatus.result ?? (rawStatus as any).analysis_result);
  const normalized = {
    ...rawStatus,
    result,
    scores: parseJsonValue(rawStatus.scores),
    security_report: parseJsonValue(rawStatus.security_report),
    market_report: parseJsonValue(rawStatus.market_report),
  } as JobStatus;
  console.debug("[analysis] API response", {
    status: normalized.status,
    result: Boolean(result),
    bugs: result?.bugs.length ?? 0,
    diffs: result?.diffs.length ?? 0,
    architectureIssues: result?.architecture?.static_issues?.length ?? 0,
    market: Boolean(result?.market_report || normalized.market_report),
  });
  return normalized;
}

export async function stopAnalysis(jobId: string): Promise<{ status: string }> {
  const res = await fetch(`${BACKEND}/api/analysis/${jobId}/stop`, {
    method: "POST",
    headers: await authHeaders(),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Unable to stop analysis: ${res.status}`);
  return body;
}

export async function deleteAnalysis(jobId: string): Promise<void> {
  const res = await fetch(`${BACKEND}/api/analysis/${jobId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Unable to delete analysis: ${res.status}`);
}

export async function startAnalysis(repoUrl: string, userId?: string | null): Promise<{ job_id: string }> {
  const headers = await authHeaders();
  const res = await fetch(`${BACKEND}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ repo_url: repoUrl, user_id: userId || null }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to start analysis: ${res.status}`);
  }
  return res.json();
}

export function createStatusStream(jobId: string, token: string): EventSource {
  return new EventSource(`${BACKEND}/api/status/${jobId}?token=${encodeURIComponent(token)}`);
}

export async function approveAndPush(jobId: string): Promise<{ pr_url: string; message: string }> {
  const res = await fetch(`${BACKEND}/api/approve/${jobId}`, { method: "POST", headers: await authHeaders() });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Approval failed: ${res.status}`);
  }
  return res.json();
}

export async function pollJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${BACKEND}/api/job/${jobId}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
  return normalizeJobStatus(await res.json());
}

export async function getAnalysis(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${BACKEND}/api/analysis/${jobId}`, { headers: await authHeaders() });
  if (!res.ok) throw new Error(`Analysis load failed: ${res.status}`);
  const data = await res.json();
  return normalizeJobStatus({
    ...data,
    all_logs: data.all_logs || data.logs || data.trace_logs || data.traceLogs || [],
    new_logs: [],
  });
}

export async function listJobs(limit = 10): Promise<JobRow[]> {
  try {
    // If Supabase url is placeholder, bypass fetching to avoid console network errors
    if (!supabase || (supabase as any).supabaseUrl?.includes("placeholder")) {
      return [];
    }

    const { data, error } = await supabase
      .from("analysis_jobs")
      .select("*")
      .order("created_at", { ascending: false })
      .limit(limit);
    
    if (error) {
      console.error("Failed to list jobs:", error);
      return [];
    }
    return data || [];
  } catch (err) {
    console.error("Error listing jobs:", err);
    return [];
  }
}

export async function listUserJobs(userId: string, limit = 20): Promise<JobRow[]> {
  if (!userId) return [];
  try {
    const res = await fetch(`${BACKEND}/api/jobs/user/${userId}?limit=${limit}`, { headers: await authHeaders() });
    if (res.ok) {
      return await res.json();
    }
  } catch (e) {
    console.error("Failed to fetch user jobs via backend API:", e);
  }
  return [];
}

export interface Profile {
  id: string;
  email: string;
  display_name: string;
  created_at?: string;
}

export async function getProfile(): Promise<Profile | null> {
  const response = await fetch(`${BACKEND}/api/profile`, { headers: await authHeaders() });
  if (!response.ok) return null;
  return response.json();
}

export async function updateProfile(fullName: string): Promise<Profile> {
  const response = await fetch(`${BACKEND}/api/profile`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...await authHeaders() },
    body: JSON.stringify({ full_name: fullName }),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Unable to update profile");
  return body;
}

export function getScoreColorClass(score: number | null): string {
  if (score === null || score === undefined) return "text-slate-400 border-slate-750 bg-slate-900/40";
  if (score >= 80) return "text-emerald-450 border-emerald-500/20 bg-emerald-500/5";
  if (score >= 60) return "text-amber-450 border-amber-500/20 bg-amber-500/5";
  return "text-rose-450 border-rose-500/20 bg-rose-500/5";
}
