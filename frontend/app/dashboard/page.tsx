"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { getUser } from "@/lib/supabase";
import { deleteAnalysis, listUserJobs } from "@/lib/api";
import type { JobRow } from "@/lib/supabase";

export default function HistoryPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("All");
  const [sort, setSort] = useState("Newest");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { getUser().then(async (user) => { if (user) setJobs(await listUserJobs(user.id, 100)); }); }, []);
  const handleDelete = async (jobId: string) => {
    if (!window.confirm("Are you sure you want to delete this repository analysis?")) return;
    setError("");
    try {
      await deleteAnalysis(jobId);
      setJobs((currentJobs) => currentJobs.filter((job) => job.id !== jobId));
      setNotice("Repository analysis deleted successfully.");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete repository analysis.");
    }
  };
  const statusLabel = (jobStatus: JobRow["status"]) => jobStatus === "done" ? "Completed" : jobStatus === "error" ? "Failed" : jobStatus === "stopped" ? "Stopped" : "Running";
  const filtered = useMemo(() => jobs.filter((job) => {
    const matchesQuery = (job.repo_name || job.repo_url).toLowerCase().includes(query.toLowerCase());
    const statusValue = status === "Completed" ? "done" : status === "Failed" ? "error" : status.toLowerCase();
    return matchesQuery && (status === "All" || job.status === statusValue);
  }).sort((a, b) => sort === "Highest Health Score" ? (b.health_score || 0) - (a.health_score || 0) : sort === "Lowest Health Score" ? (a.health_score || 0) - (b.health_score || 0) : sort === "Oldest" ? a.created_at.localeCompare(b.created_at) : b.created_at.localeCompare(a.created_at)), [jobs, query, status, sort]);

  return <main className="saas-page"><div className="page-container"><div className="page-heading"><div><p className="eyebrow">Workspace archive</p><h1>Analysis History</h1><p className="page-subtitle">View and revisit your previous repository analyses.</p></div><span className="count-label">{jobs.length} analyses</span></div>
    <section className="toolbar-panel"><div className="search-field"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search repositories..." aria-label="Search repositories" /></div><div className="filter-group">{["All", "Completed", "Failed", "Running", "Stopped"].map((item) => <button key={item} className={status === item ? "filter-button active" : "filter-button"} onClick={() => setStatus(item)}>{item}</button>)}</div><select className="select-control" value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Sort analyses"><option>Newest</option><option>Oldest</option><option>Highest Health Score</option><option>Lowest Health Score</option></select></section>
    {notice && <div className="success-banner" role="status">{notice}</div>}{error && <div className="error-banner" role="alert">{error}</div>}<section className="data-panel"><div className="data-table-wrap"><table className="data-table"><thead><tr><th>Repository</th><th>Analyzed on</th><th>Health score</th><th>Issues</th><th>Security risks</th><th>Status</th><th>Actions</th></tr></thead><tbody>{filtered.map((job) => <tr key={job.id}><td><strong>{job.repo_name || job.repo_url.replace(/^https?:\/\/(www\.)?github.com\//, "")}</strong><small>{job.framework || "Repository analysis"}</small></td><td>{job.created_at ? new Date(job.created_at).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" }) : "—"}</td><td><span className="score-value">{job.health_score !== null ? `${job.health_score}/100` : "Pending"}</span></td><td>Available in report</td><td>Available in report</td><td><span className={`table-status ${job.status}`}>{statusLabel(job.status)}</span></td><td><div className="table-actions"><button className="secondary-button compact" onClick={() => router.push(`/analyze/${job.id}`)}>View</button><button className="danger-button compact" onClick={() => handleDelete(job.id)}>Delete</button></div></td></tr>)}</tbody></table></div>{filtered.length === 0 && <div className="empty-history">No analyses match your current filters.</div>}</section>
  </div></main>;
}
