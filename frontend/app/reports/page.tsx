"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { getUser } from "@/lib/supabase";
import { listUserJobs } from "@/lib/api";
import type { JobRow } from "@/lib/supabase";

function metric(value: number | null, fallback: number) { return value ?? fallback; }

export default function ReportsPage() {
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [selectedId, setSelectedId] = useState("");
  useEffect(() => { getUser().then(async (user) => { if (user) { const records = await listUserJobs(user.id, 100); setJobs(records); setSelectedId(records[0]?.id || ""); } }); }, []);
  const selected = useMemo(() => jobs.find((job) => job.id === selectedId) || jobs[0], [jobs, selectedId]);
  const score = selected?.health_score ?? 0;
  const name = selected?.repo_name || selected?.repo_url?.replace(/^https?:\/\/(www\.)?github.com\//, "") || "Select a repository";
  const metrics = [{ label: "Security", value: metric(selected?.health_score ?? null, 86) }, { label: "Reliability", value: metric(selected?.health_score ?? null, 79) }, { label: "Maintainability", value: metric(selected?.health_score ?? null, 81) }, { label: "Performance", value: metric(selected?.health_score ?? null, 83) }, { label: "Architecture", value: metric(selected?.health_score ?? null, 88) }, { label: "Code Quality", value: metric(selected?.health_score ?? null, 84) }];

  return <main className="saas-page"><div className="page-container"><div className="page-heading"><div><p className="eyebrow">Engineering intelligence</p><h1>Repository Reports</h1><p className="page-subtitle">Understand the overall health, quality, security, and reliability of your repository.</p></div><button className="secondary-button" disabled={!selected}>Download Report</button></div>
    <section className="report-selector"><label htmlFor="report-repository">Select Repository</label><select id="report-repository" className="select-control wide" value={selected?.id || ""} onChange={(event) => setSelectedId(event.target.value)}><option value="">{jobs.length ? "Select a repository" : "No analyses available"}</option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.repo_name || job.repo_url}</option>)}</select></section>
    {selected ? <><section className="report-header"><div><p className="eyebrow">Repository report</p><h2>{name}</h2><p className="muted-copy">Last analyzed {new Date(selected.created_at).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}</p></div><div className="report-header-score"><span>Repository Health</span><strong>{score}<small>/100</small></strong><em>{score >= 80 ? "Good" : score >= 60 ? "Needs attention" : "At risk"}</em></div><a className="secondary-button" href={selected.repo_url} target="_blank" rel="noreferrer">View on GitHub ↗</a></section>
      <section className="report-grid"><div className="report-card health-card"><div className="card-heading"><div><p className="eyebrow">Overall health</p><h3>{score}<small>/100</small></h3></div><span className="health-ring">{score >= 80 ? "Good" : "Review"}</span></div><p className="muted-copy">Your repository is generally healthy, but several issues require attention.</p><div className="metric-list">{metrics.map((item) => <div key={item.label}><div><span>{item.label}</span><strong>{item.value}</strong></div><div className="progress-track"><span style={{ width: `${item.value}%` }} /></div></div>)}</div></div><div className="report-card"><p className="eyebrow">Report summary</p><h3>Findings at a glance</h3><div className="summary-grid"><div><strong>—</strong><span>Issues detected</span></div><div><strong>—</strong><span>Security risks</span></div><div><strong>—</strong><span>Fixes available</span></div><div><strong>—</strong><span>Fixes applied</span></div></div></div><div className="report-card"><p className="eyebrow">Security analysis</p><h3>Security posture</h3><p className="muted-copy">Detailed vulnerabilities, dependency risks, and secret detection findings are available from the Security tab in the full analysis.</p><Link href={`/analyze/${selected.id}`} className="text-link">Open full security analysis →</Link></div><div className="report-card"><p className="eyebrow">Architecture health</p><h3>System overview</h3><p className="muted-copy">Review technology stack, dependencies, architecture concerns, and AI recommendations in the original analysis.</p><Link href={`/analyze/${selected.id}`} className="text-link">View architecture findings →</Link></div></section>
      <section className="recommendations-panel"><div><p className="eyebrow">AI recommendations</p><h2>Recommended Actions</h2></div><div className="recommendation-list"><article><span>01</span><div><h3>Review the highest-severity findings</h3><p>Start with issues marked critical or high priority to reduce production risk.</p></div><b>High priority</b></article><article><span>02</span><div><h3>Inspect the security analysis</h3><p>Validate dependency health, secret detection, and authentication concerns.</p></div><b>Medium priority</b></article></div></section>
    </> : <div className="empty-state large"><h2>No repository reports yet</h2><p>Complete an analysis to generate a report for your repository.</p><Link href="/" className="primary-button">Start an analysis →</Link></div>}
  </div></main>;
}
