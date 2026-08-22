"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import RepoInput from "@/components/RepoInput";
import { getUser } from "@/lib/supabase";
import { listUserJobs, startAnalysis } from "@/lib/api";
import type { JobRow } from "@/lib/supabase";

const pipeline = ["Scanner", "Explorer", "Auditor", "Architect", "Executor", "Market"];
const tabs = ["Live Trace", "Browser", "Issues", "Fixes", "Security", "Architecture", "Market"];

export default function AnalysisPage() {
	const router = useRouter();
	const [url, setUrl] = useState("");
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);
	const [jobs, setJobs] = useState<JobRow[]>([]);
	const [activeTab, setActiveTab] = useState("Live Trace");

	useEffect(() => {
		getUser().then(async (user) => {
			if (user) setJobs(await listUserJobs(user.id, 6));
		});
	}, []);

	const analyze = async () => {
		const repository = url.trim();
		if (!repository.includes("github.com")) {
			setError("Enter a valid GitHub repository URL.");
			return;
		}
		setError("");
		setLoading(true);
		try {
			const user = await getUser();
			const result = await startAnalysis(repository, user?.id);
			router.push(`/analyze/${result.job_id}`);
		} catch (requestError) {
			setError(requestError instanceof Error ? requestError.message : "Unable to start analysis.");
			setLoading(false);
		}
	};

	return (
		<main className="saas-page">
			<div className="page-container">
				<div className="page-heading">
					<div><p className="eyebrow">Repository intelligence</p><h1>Analyze repository</h1><p className="page-subtitle">Run a complete engineering, security, and product audit from one workspace.</p></div>
					<span className="status-pill status-ready"><span />System ready</span>
				</div>

				<section className="input-panel">
					<div><label htmlFor="repository-url">GitHub Repository URL</label><p>Connect a public repository to begin a new analysis.</p></div>
					<div className="repo-input-row"><input id="repository-url" value={url} onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => event.key === "Enter" && analyze()} placeholder="https://github.com/username/repository" /><button className="primary-button" onClick={analyze} disabled={loading}>{loading ? "Starting..." : "Analyze Repository  →"}</button></div>
					{error && <p className="form-error" role="alert">{error}</p>}
				</section>

				<section className="section-block">
					<div className="section-title-row"><div><p className="eyebrow">Analysis workflow</p><h2>Autonomous Architect Pipeline</h2></div><span className="muted-label">6 agents · sequential execution</span></div>
					<div className="pipeline-track">{pipeline.map((agent, index) => <div className="pipeline-step-wrap" key={agent}><div className={`pipeline-step ${index === 0 ? "pipeline-current" : ""}`}><span className="pipeline-number">{String(index + 1).padStart(2, "0")}</span><strong>{agent}</strong><small>{index === 0 ? "Ready" : "Pending"}</small></div>{index < pipeline.length - 1 && <span className="pipeline-arrow">→</span>}</div>)}</div>
				</section>

				<section className="workspace-panel">
					<div className="workspace-tabs" role="tablist">{tabs.map((tab) => <button key={tab} onClick={() => setActiveTab(tab)} className={activeTab === tab ? "workspace-tab active" : "workspace-tab"}>{tab}</button>)}</div>
					<div className="workspace-grid">
						<div className="workspace-main">
							<div className="section-title-row"><div><p className="eyebrow">Live workspace</p><h2>{activeTab}</h2></div><span className="live-indicator"><span />Waiting for analysis</span></div>
							{activeTab === "Live Trace" ? <>
								<div className="subsection-heading"><h3>Agent Registry</h3><span className="muted-label">Current run</span></div>
								<div className="agent-registry">{pipeline.map((agent, index) => <div className="agent-row" key={agent}><span className={`agent-state ${index === 0 ? "complete" : index === 1 ? "running" : "pending"}`}>{index === 0 ? "✓" : index === 1 ? "•" : "–"}</span><strong>{agent}</strong><span className="agent-status">{index === 0 ? "Completed" : index === 1 ? "Running" : "Pending"}</span></div>)}</div>
								<div className="subsection-heading trace-heading"><h3>Live Trace Output</h3><span className="muted-label">Awaiting repository</span></div>
								<div className="trace-output"><div><time>10:15:30</time><b>SCANNER</b><span>Repository analysis will appear here.</span></div><div><time>10:15:32</time><b>SCANNER</b><span>Enter a GitHub URL above to start the pipeline.</span></div></div>
							</> : <div className="empty-workspace"><span className="empty-icon">{activeTab === "Browser" ? "◫" : activeTab === "Issues" ? "!" : "✓"}</span><h3>{activeTab} results appear after analysis</h3><p>Start an analysis to populate this workspace with repository-specific findings.</p></div>}
						</div>
						<aside className="repository-card"><div className="section-title-row"><h3>Repository Information</h3><span className="info-icon">i</span></div><dl><div><dt>Repository</dt><dd>Not selected</dd></div><div><dt>Branch</dt><dd>—</dd></div><div><dt>Language</dt><dd>Detected after scan</dd></div><div><dt>Visibility</dt><dd>Public</dd></div></dl><div className="repository-note">Analysis results, screenshots, and reports remain scoped to your account.</div></aside>
					</div>
				</section>

				<section className="section-block history-preview"><div className="section-title-row"><div><p className="eyebrow">Your workspace</p><h2>Recent analyses</h2></div><Link href="/dashboard" className="text-link">View history →</Link></div>{jobs.length ? <div className="compact-table">{jobs.map((job) => <button key={job.id} onClick={() => router.push(`/analyze/${job.id}`)}><span>{job.repo_name || job.repo_url.replace(/^https?:\/\/(www\.)?github.com\//, "")}</span><span className={`table-status ${job.status}`}>{job.status}</span><span>{job.health_score ? `${job.health_score}/100` : "Pending"}</span><span>View →</span></button>)}</div> : <div className="empty-history">No analyses yet. Your completed repository audits will appear here.</div>}</section>
			</div>
		</main>
	);
}
