"use client";

import { useEffect, useState, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import {
  createStatusStream, approveAndPush, getScoreColorClass, getAnalysis, pollJobStatus, stopAnalysis, normalizeJobStatus,
  type LogEntry, type JobResult, type JobStatus, type Bug, type ArchitectureIssue, type Diff,
  type Scores, type SecurityFinding, type SecurityReport, type MarketReport, type IssueItem
} from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import AgentCard from "@/components/AgentCard";
import { getAccessToken } from "@/lib/supabase";

// Dynamic import of Diff Viewer to prevent SSR issues
const ReactDiffViewer = dynamic(() => import("react-diff-viewer-continued"), {
  ssr: false,
  loading: () => <div className="p-8 text-center text-slate-500 font-mono text-sm">Loading diff viewer...</div>
});

const AGENTS = [
  { name: "Scanner", emoji: "📚", color: "cyan", hex: "#06B6D4" },
  { name: "Explorer", emoji: "🌐", color: "emerald", hex: "#10B981" },
  { name: "Auditor", emoji: "🔍", color: "amber", hex: "#F59E0B" },
  { name: "Architect", emoji: "🏗️", color: "violet", hex: "#7C3AED" },
  { name: "Executor", emoji: "🤖", color: "rose", hex: "#F43F5E" },
];

const ALL_SEVEN_AGENTS = [
  { name: "Scanner", emoji: "📚" },
  { name: "Explorer", emoji: "🌐" },
  { name: "Auditor", emoji: "🔍" },
  { name: "Architect", emoji: "🏗️" },
  { name: "Executor", emoji: "🤖" },
  { name: "Market", emoji: "📊" },
  { name: "System", emoji: "⚙️" }
];

const LOG_LEVEL_COLORS: Record<string, string> = {
  info: "text-slate-350",
  success: "text-emerald-400 font-semibold",
  warning: "text-amber-400",
  error: "text-rose-400 font-bold",
};

type Tab = "trace" | "browser" | "bugs" | "diffs" | "security" | "architecture" | "market";

export default function AnalyzePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<"running" | "done" | "stopped" | "error">("running");
  const [result, setResult] = useState<JobResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [activeTab, setActiveTab] = useState<Tab>("trace");
  const [activeAgent, setActiveAgent] = useState("Scanner");
  const [approving, setApproving] = useState(false);
  const [prUrl, setPrUrl] = useState("");
  const [approveError, setApproveError] = useState("");
  const [isMounted, setIsMounted] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [stopNotice, setStopNotice] = useState("");
  const [historical, setHistorical] = useState(false);
  const [analysisLoaded, setAnalysisLoaded] = useState(false);
  const isHistoryView = analysisLoaded && historical;

  // New state variables
  const [scores, setScores] = useState<Scores | null>(null);
  const [securityReport, setSecurityReport] = useState<SecurityReport | null>(null);
  const [marketReport, setMarketReport] = useState<MarketReport | null>(null);
  const [screenshotB64, setScreenshotB64] = useState<string | null>(null);

  const applyAnalysisState = (data: JobStatus) => {
    const nextResult = data.result;
    const nextScores = nextResult?.scores ?? data.scores ?? null;
    const nextSecurityReport = nextResult?.security_report ?? data.security_report ?? null;
    const nextMarketReport = nextResult?.market_report ?? data.market_report ?? null;
    const nextScreenshot = nextResult?.screenshot_b64 ?? data.screenshot_b64 ?? null;
    console.debug("[analysis] applying state", {
      status: data.status,
      logs: data.all_logs?.length ?? 0,
      bugs: nextResult?.bugs.length ?? 0,
      diffs: nextResult?.diffs.length ?? 0,
      architectureIssues: nextResult?.architecture?.static_issues?.length ?? 0,
      market: Boolean(nextMarketReport),
    });
    setStatus(data.status);
    setResult(nextResult);
    setLogs(data.all_logs || []);
    setScores(nextScores);
    setSecurityReport(nextSecurityReport);
    setMarketReport(nextMarketReport);
    setScreenshotB64(nextScreenshot);
    if (data.pr_url) setPrUrl(data.pr_url);
    if (data.error) setErrorMsg(data.error);
    if (data.status !== "running") {
      setHistorical(true);
      setActiveTab("bugs");
    }
  };

  useEffect(() => {
    setIsMounted(true);
  }, []);

  useEffect(() => {
    if (!id) return;
    getAnalysis(id).then((data) => {
      applyAnalysisState(data);
      setAnalysisLoaded(true);
    }).catch(() => pollJobStatus(id).then((data) => {
      applyAnalysisState(data);
      setAnalysisLoaded(true);
    }).catch(() => setAnalysisLoaded(true)));
  }, [id]);

  useEffect(() => {
    if (!id || !analysisLoaded || historical) return;
    let es: EventSource | null = null;
    getAccessToken().then((token) => {
      if (!token) {
        router.replace("/login");
        return;
      }
      const stream = createStatusStream(id, token);
      es = stream;

    stream.onmessage = (e: MessageEvent) => {
      try {
        const data = normalizeJobStatus(JSON.parse(e.data));
        applyAnalysisState(data);

        const allLogs: LogEntry[] = data.all_logs || [];
        if (allLogs.length > 0) {
          // Determine active agent from last log entry where agent !== "System"
          for (let i = allLogs.length - 1; i >= 0; i--) {
            const agent = allLogs[i].agent;
            if (agent !== "System") {
              setActiveAgent(agent);
              break;
            }
          }
        }

        if (data.error) setErrorMsg(data.error);
        if (data.status === "done" || data.status === "stopped" || data.status === "error") stream.close();
      } catch (err) {
        // Ignore parse errors
      }
    };

    stream.onerror = () => {
      stream.close();
    };
    });

    return () => es?.close();
  }, [id, historical, analysisLoaded]);

  const handleApprove = async () => {
    setApproving(true);
    setApproveError("");
    try {
      const { pr_url } = await approveAndPush(id);
      setPrUrl(pr_url);
    } catch (e: any) {
      setApproveError(e.message || "Failed to create PR");
    } finally {
      setApproving(false);
    }
  };

  const handleStop = async () => {
    if (!window.confirm("Stop the current repository analysis?")) return;
    setStopping(true);
    try {
      await stopAnalysis(id);
      setStatus("stopped");
      setStopNotice("Analysis stopped successfully.");
    } catch (stopError) {
      setErrorMsg(stopError instanceof Error ? stopError.message : "Unable to stop analysis.");
    } finally {
      setStopping(false);
    }
  };

  const getAgentIndex = (name: string) => {
    return AGENTS.findIndex(a => a.name === name);
  };

  const currentAgentIdx = getAgentIndex(activeAgent);

  const tabs: { id: Tab; label: string }[] = [
    { id: "trace", label: "⚙️ Live Trace" },
    { id: "browser", label: "🖥️ Browser" },
    { id: "bugs", label: "🐛 Issues" },
    { id: "diffs", label: "📝 Fixes" },
    { id: "security", label: "🔒 Security" },
    { id: "architecture", label: "🏗️ Architecture" },
    { id: "market", label: "📊 Market" },
  ];

  const getTabBadge = (tabId: Tab) => {
    if (tabId === "bugs" && result?.bugs && result.bugs.filter(isRenderableIssue).length > 0) {
      return (
        <span className="ml-1.5 bg-slate-800 text-cyan-400 text-[10px] px-2 py-0.5 rounded-full border border-slate-700 font-mono">
          {result.bugs.filter(isRenderableIssue).length}
        </span>
      );
    }
    if (tabId === "diffs" && result?.diffs && result.diffs.length > 0) {
      return (
        <span className="ml-1.5 bg-slate-800 text-cyan-400 text-[10px] px-2 py-0.5 rounded-full border border-slate-700 font-mono">
          {result.diffs.length}
        </span>
      );
    }
    if (tabId === "security" && securityReport && securityReport.total_findings > 0) {
      return (
        <span className="ml-1.5 bg-rose-500/10 border border-rose-500/20 text-rose-400 text-[10px] px-2 py-0.5 rounded-full font-mono font-bold animate-pulse">
          {securityReport.total_findings}
        </span>
      );
    }
    if (tabId === "browser" && screenshotB64) {
      return (
        <span className="ml-1.5 flex h-2.5 w-2.5 relative shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-450 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
        </span>
      );
    }
    if (tabId === "market" && marketReport) {
      return (
        <span className="ml-1.5 flex h-2.5 w-2.5 relative shrink-0">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-450 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
        </span>
      );
    }
    return null;
  };

  console.debug("[analysis] tab render", {
    activeTab,
    bugs: result?.bugs?.length ?? 0,
    diffs: result?.diffs?.length ?? 0,
    architectureIssues: result?.architecture?.static_issues?.length ?? 0,
    market: Boolean(result?.market_report || marketReport),
  });

  return (
    <main className="min-h-screen bg-[#020817] text-slate-100 flex flex-col font-sans">
      {/* Dynamic Header */}
      <header className="border-b border-slate-800/60 bg-slate-900/35 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 py-4 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button 
              onClick={() => router.push("/")} 
              className="text-slate-400 hover:text-white transition-colors p-2 hover:bg-slate-800/40 rounded-xl"
            >
              ← Back
            </button>
            <div>
              <h1 className="font-display font-bold text-lg text-white tracking-wide">
                🤖 Autonomous Architect Pipeline
              </h1>
              <p className="text-slate-500 font-mono text-xs truncate max-w-[280px] sm:max-w-md mt-0.5">
                {result?.repo_url || `Job ID: ${id}`}
              </p>
            </div>
          </div>

          {/* Running status badge + health badge */}
          <div className="flex items-center gap-3">
            {scores && scores.health !== null && (
              <div className={`flex items-center gap-1.5 rounded-xl border px-3.5 py-1.5 shadow-sm text-xs font-mono font-bold ${getScoreColorClass(scores.health)}`}>
                <span className="text-[10px] font-display font-semibold uppercase tracking-wider text-slate-400">Health:</span>
                <span>{scores.health}/100</span>
              </div>
            )}
            <StatusBadge status={status} />
            {status === "running" && !stopping && <button className="danger-button compact" onClick={handleStop} disabled={stopping}>Stop Analysis</button>}
          </div>
        </div>
      </header>

      <div className="flex-1 max-w-7xl w-full mx-auto p-6 space-y-8">
        
        {stopNotice && <div className="success-banner" role="status">{stopNotice}</div>}

        {/* Repository Health Dashboard (Visible on all tabs) */}
        <ScoresDashboard scores={scores} />

        {/* 7-Agent Row indicator */}
        <AgentRow logs={logs} status={status} activeAgentName={activeAgent} />

        {/* Real-time interactive neural SVG + status tracker */}
        <div className="glass border border-slate-800/40 rounded-2xl p-6 shadow-xl relative overflow-hidden">
          <div className="absolute top-3 left-4 flex items-center gap-2 font-mono text-[9px] text-slate-500 uppercase tracking-widest">
            <span className="w-1.5 h-1.5 bg-cyan-400 rounded-full animate-ping" />
            Live Agent Sync Node
          </div>

          {/* Head SVG Neural Chain */}
          <div className="h-24 w-full mt-4">
            <svg className="w-full h-full" viewBox="0 0 800 80" preserveAspectRatio="xMidYMid meet">
              {/* Connecting dashed line */}
              <line
                x1="80"
                y1="35"
                x2="720"
                y2="35"
                stroke="#1e293b"
                strokeWidth="2"
                strokeDasharray="4,4"
              />

              {/* Progress connection line */}
              {currentAgentIdx >= 0 && (
                <line
                  x1="80"
                  y1="35"
                  x2={80 + currentAgentIdx * 160}
                  y2="35"
                  stroke={AGENTS[currentAgentIdx].hex}
                  strokeWidth="3.5"
                  strokeLinecap="round"
                  className="transition-all duration-700"
                />
              )}

              {/* Dynamic node circles */}
              {AGENTS.map((agent, idx) => {
                const cx = 80 + idx * 160;
                const cy = 35;
                const isRunning = activeAgent === agent.name && status === "running";
                const isCompleted = getAgentIndex(activeAgent) > idx || status === "done";

                return (
                  <g key={idx}>
                    {isRunning && (
                      <circle
                        cx={cx}
                        cy={cy}
                        r="20"
                        fill="none"
                        stroke={agent.hex}
                        strokeWidth="1.5"
                        className="animate-ping"
                      />
                    )}
                    <circle
                      cx={cx}
                      cy={cy}
                      r="12"
                      fill={isRunning ? agent.hex : isCompleted ? "#10B981" : "#0f172a"}
                      stroke={isRunning ? "#fff" : isCompleted ? "#047857" : "rgba(255,255,255,0.08)"}
                      strokeWidth="2"
                      className="transition-all duration-500"
                    />
                    <text
                      x={cx}
                      y={cy + 4}
                      textAnchor="middle"
                      className="text-xs pointer-events-none select-none"
                    >
                      {agent.emoji}
                    </text>
                    <text
                      x={cx}
                      y={cy + 25}
                      textAnchor="middle"
                      fill={isRunning ? "#f8fafc" : isCompleted ? "#10B981" : "#64748b"}
                      className="text-[9px] font-display font-bold uppercase tracking-wider transition-colors duration-500"
                    >
                      {agent.name}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        {/* Live Grid layout: left is list of Agent status cards, right is log viewer / results */}
        <div className="analysis-workspace-grid grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
          
          {/* Left: Agent status sidebar cards */}
          <div className="analysis-agent-panel lg:col-span-1 space-y-4">
            <h3 className="font-display font-bold text-xs uppercase tracking-widest text-slate-400">
              Agent Registry
            </h3>
            {AGENTS.map((agent) => {
              const agentLogs = logs.filter(l => l.agent === agent.name);
              const lastLog = agentLogs.length > 0 ? agentLogs[agentLogs.length - 1] : undefined;
              const isCurrent = activeAgent === agent.name && status === "running";
              const isFinished = getAgentIndex(activeAgent) > getAgentIndex(agent.name) || status === "done";

              return (
                <AgentCard
                  key={agent.name}
                  name={agent.name}
                  emoji={agent.emoji}
                  description={
                    agent.name === "Scanner" ? "Scans repository layout & languages" :
                    agent.name === "Explorer" ? "Drives browser session with Playwright" :
                    agent.name === "Auditor" ? "Analyzes runtime crash logs" :
                    agent.name === "Architect" ? "Checks codebase structure quality" :
                    "Generates file edits and commits fixes"
                  }
                  active={isCurrent}
                  done={isFinished}
                  lastMessage={lastLog?.message}
                />
              );
            })}
          </div>

          {/* Right: Main display content panel */}
          <div className="analysis-content-panel lg:col-span-2 space-y-6">
            
            {/* Tabs */}
            <div className="flex flex-wrap gap-1 border-b border-slate-800/80">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-3 text-xs font-display font-bold uppercase tracking-wider transition-colors border-b-2 -mb-px flex items-center ${
                    activeTab === tab.id
                      ? "border-cyan-500 text-cyan-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <span>{tab.label}</span>
                  {getTabBadge(tab.id)}
                </button>
              ))}
            </div>

            {/* Tab 1: Trace Logs */}
            {activeTab === "trace" && (
              <div className="glass border border-slate-800/50 rounded-2xl p-5 shadow-inner">
                <div className="flex items-center justify-between mb-4 border-b border-slate-800 pb-3">
                  <div className="text-xs font-mono text-slate-500 uppercase tracking-wider">
                    Console Trace Output
                  </div>
                  <div className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-ping" />
                </div>
                <div className="h-[380px] overflow-y-auto font-mono text-xs leading-relaxed space-y-2 pr-2">
                  {logs.length === 0 && (
                    <div className="text-slate-650 italic text-center py-12">
                      {isHistoryView ? "No trace logs available." : "Pipeline initialization in progress..."}
                    </div>
                  )}
                  {logs.map((log, idx) => (
                    <div key={idx} className="flex gap-2 items-start py-0.5">
                      <span className="text-slate-600 select-none text-[10px] w-6 text-right shrink-0">
                        {idx + 1}
                      </span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider shrink-0 bg-slate-900 border border-slate-800 text-slate-405`}>
                        {log.agent}
                      </span>
                      <span className={`${LOG_LEVEL_COLORS[log.level] || "text-slate-300"} break-all`}>
                        {log.message}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Tab 2: Browser Preview */}
            {activeTab === "browser" && (
              <BrowserPreview screenshotB64={screenshotB64} historical={isHistoryView} />
            )}

            {/* Tab 3: Bugs Cards */}
            {activeTab === "bugs" && (
              <div className="space-y-4">
                {!result && (
                  <div className="glass border border-slate-800/40 rounded-2xl py-16 text-center">
                    <p className="text-slate-550 text-sm font-mono animate-pulse">
                      {status === "running" ? "Agents are scanning for runtime bugs..." : "No bugs analyzed."}
                    </p>
                  </div>
                )}
                {result?.bugs?.filter(isRenderableIssue).length === 0 && (
                  <div className="glass border border-slate-800/40 rounded-2xl py-16 text-center space-y-3">
                    <div className="text-5xl">✨</div>
                    <h4 className="font-display font-bold text-slate-200 text-lg">Codebase Clean!</h4>
                    <p className="text-slate-500 text-xs max-w-sm mx-auto">
                      Explorer navigated all endpoints successfully without encountering uncaught client crashes.
                    </p>
                  </div>
                )}
                {result && result.bugs && result.bugs.filter(isRenderableIssue).map((bug, idx) => (
                  <EnhancedIssueCard key={idx} issue={normalizeIssue(bug)} />
                ))}
              </div>
            )}

            {/* Tab 4: Code Diffs Split Viewer */}
            {activeTab === "diffs" && (
              <div className="space-y-4">
                {!result && (
                  <div className="glass border border-slate-800/40 rounded-2xl py-16 text-center">
                    <p className="text-slate-500 text-sm font-mono">
                      {status === "running" ? "Generating code edits with Gemini..." : "Fix data is unavailable."}
                    </p>
                  </div>
                )}

                {result && !result.diffs?.length && result.bugs?.filter(isRenderableIssue).length === 0 && (
                  <div className="glass border border-amber-500/20 rounded-2xl p-6 shadow-xl space-y-3">
                    <h4 className="font-display font-bold text-amber-400 text-base">No automated fix available</h4>
                    <p className="text-slate-400 text-xs leading-relaxed">{result.bugs?.filter(isRenderableIssue).length ? "Issues were detected, but no generated diff was saved for this analysis. Manual intervention is required." : "No generated diffs were saved for this analysis."}</p>
                    {result.bugs?.filter(isRenderableIssue).length > 0 && <div className="flex flex-wrap gap-3">
                      <button className="secondary-button compact" disabled title="No generated diff is available">Approve Fix</button>
                      <button className="secondary-button compact" disabled title="No generated diff is available">Push Fix</button>
                      <button className="secondary-button compact" disabled title="No generated diff is available">Create PR</button>
                    </div>}
                  </div>
                )}
                
                {isMounted && result?.diffs?.map((diff, idx) => (
                  <DiffCollapse key={idx} diff={diff} />
                ))}

                {/* Human approval button */}
                {result?.diffs && result.diffs.length > 0 && !prUrl && (
                  <div className="glass border border-slate-700/50 rounded-2xl p-6 shadow-xl space-y-4 mt-8">
                    <div>
                      <h4 className="font-display font-bold text-slate-200 text-base">
                        Awaiting Human Gate Approval
                      </h4>
                      <p className="text-slate-500 text-xs leading-relaxed mt-1">
                        Review the code diffs above. Upon approval, RepoGuardian will create a new git branch, apply the changes, and create a Pull Request on your repository.
                      </p>
                    </div>

                    {approveError && (
                      <p className="text-rose-450 font-mono text-xs">{approveError}</p>
                    )}

                    <div className="flex flex-wrap gap-3">
                    <button onClick={handleApprove} disabled={approving} className="relative group active:scale-95 transition-transform">
                      <div className="absolute -inset-0.5 bg-gradient-to-r from-emerald-500 to-cyan-500 rounded-xl opacity-45 group-hover:opacity-75 blur-[3px]" />
                      <div className="relative bg-gradient-to-r from-emerald-500 to-emerald-400 text-slate-950 font-bold px-8 py-3.5 rounded-xl text-sm transition-all flex items-center justify-center gap-2">
                        {approving ? (
                          <>
                            <svg className="animate-spin w-4 h-4 text-slate-950" viewBox="0 0 24 24" fill="none">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                            <span>Creating Pull Request...</span>
                          </>
                        ) : (
                          <>
                            <span>Approve Fix</span>
                            <span>✓</span>
                          </>
                        )}
                      </div>
                    </button>
                    <button onClick={handleApprove} disabled={approving} className="secondary-button compact">Push Fix</button>
                    <button onClick={handleApprove} disabled={approving} className="secondary-button compact">Create PR</button>
                    </div>
                  </div>
                )}

                {/* PR created alert box */}
                {prUrl && (
                  <div className="glass border border-emerald-500/40 bg-emerald-500/5 rounded-2xl p-6 shadow-xl space-y-3">
                    <h4 className="font-display font-bold text-emerald-400 text-lg flex items-center gap-2">
                      🎉 PR Created Successfully!
                    </h4>
                    <p className="text-slate-300 text-sm">
                      The branch has been pushed and a PR is open:
                    </p>
                    <a
                      href={prUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-cyan-400 underline font-mono text-xs break-all hover:text-cyan-300 block"
                    >
                      {prUrl}
                    </a>
                  </div>
                )}
              </div>
            )}

            {/* Tab 5: Security Auditing */}
            {activeTab === "security" && (
              <SecurityPanel report={securityReport} historical={isHistoryView} />
            )}

            {/* Tab 6: Architecture Review Details */}
            {activeTab === "architecture" && (
              <div className="space-y-4">
                {!result ? (
                  <div className="glass border border-slate-800/40 rounded-2xl py-16 text-center">
                    <p className="text-slate-500 text-sm font-mono">
                      {isHistoryView ? "No architecture findings available." : "Running static analysis checks..."}
                    </p>
                  </div>
                ) : (
                  <ArchitecturePanel result={result} historical={isHistoryView} />
                )}
              </div>
            )}

            {/* Tab 7: Market strategist */}
            {activeTab === "market" && (
              <MarketPanel report={marketReport} historical={isHistoryView} />
            )}

          </div>
        </div>

        {/* Global Pipeline error banner */}
        {status === "error" && errorMsg && (
          <div className="glass border border-rose-500/40 bg-rose-500/5 rounded-2xl p-5 shadow-lg space-y-2">
            <h4 className="font-display font-bold text-rose-400 text-sm flex items-center gap-2">
              ⚠️ Pipeline Failed
            </h4>
            <p className="text-slate-400 text-xs font-mono">{errorMsg}</p>
            <p className="text-slate-550 text-xs">
              Check if the repository URL is correct, exists publicly, and contains a buildable stack.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}

// ── Sub-components ──────────────────────────────────────────────────────────

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return null;
  const classes: Record<string, string> = {
    "Approved": "bg-emerald-500/10 border border-emerald-500/20 text-emerald-450",
    "Approved with Caution": "bg-amber-500/10 border border-amber-500/20 text-amber-450",
    "Needs Review": "bg-blue-500/10 border border-blue-500/20 text-blue-400",
    "Rejected": "bg-rose-500/10 border border-rose-500/20 text-rose-450",
  };
  const label = verdict;
  const emoji = verdict === "Approved" ? "✅" : verdict === "Approved with Caution" ? "⚠️" : verdict === "Needs Review" ? "🔍" : "❌";
  
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded border uppercase tracking-wider shrink-0 ${classes[verdict] || "bg-slate-800 border-slate-700 text-slate-400"}`}>
      {emoji} {label}
    </span>
  );
}

function ScoreRing({ score, label, size = "md" }: { score: number | null; label: string; size?: "sm" | "md" }) {
  const radius = size === "sm" ? 24 : 35;
  const strokeWidth = size === "sm" ? 6 : 8;
  const circumference = 2 * Math.PI * radius;
  const validScore = score !== null && score !== undefined ? score : 0;
  
  let color = "#64748b"; // grey if null
  if (score !== null && score !== undefined) {
    if (score >= 80) {
      color = "#10b981"; // green
    } else if (score >= 60) {
      color = "#f59e0b"; // amber
    } else {
      color = "#ef4444"; // red
    }
  }

  const offset = circumference - (validScore / 100) * circumference;
  const sizeClass = size === "sm" ? "w-16 h-16" : "w-24 h-24";
  const textClass = size === "sm" ? "text-sm" : "text-xl";

  return (
    <div className="flex flex-col items-center justify-center text-center">
      <div className={`relative flex items-center justify-center shrink-0 ${sizeClass}`}>
        <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
          <circle
            cx="50"
            cy="50"
            r={radius}
            fill="transparent"
            stroke="#1e293b"
            strokeWidth={strokeWidth}
          />
          {score !== null && (
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="transparent"
              stroke={color}
              strokeWidth={strokeWidth}
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              strokeLinecap="round"
              className="score-ring-path transition-all duration-1000 ease-out"
            />
          )}
        </svg>
        <div className="absolute flex flex-col items-center justify-center text-center">
          <span className={`font-mono font-black ${textClass} text-white`}>
            {score !== null && score !== undefined ? score : "—"}
          </span>
        </div>
      </div>
      <span className="text-[10px] text-slate-400 font-bold uppercase tracking-wider mt-2 max-w-[80px] truncate" title={label}>
        {label}
      </span>
    </div>
  );
}

function ScoresDashboard({ scores }: { scores: Scores | null }) {
  if (!scores) {
    return (
      <div className="glass border border-slate-800/40 rounded-2xl p-6 text-center shadow-xl">
        <p className="text-slate-500 text-xs font-mono animate-pulse">
          Repository health scores will load when Auditor completes scanning...
        </p>
      </div>
    );
  }

  return (
    <div className="glass border border-slate-700/50 rounded-2xl p-6 shadow-xl space-y-4">
      <h3 className="font-display font-bold text-xs uppercase tracking-widest text-slate-450">
        Repository Health Dashboard
      </h3>
      <div className="flex flex-wrap items-center justify-around gap-6 py-2">
        <ScoreRing score={scores.health} label="Health" />
        <ScoreRing score={scores.code_quality} label="Code Quality" />
        <ScoreRing score={scores.maintainability} label="Maintainability" />
        <ScoreRing score={scores.documentation} label="Documentation" />
        <ScoreRing score={scores.security} label="Security" />
      </div>
    </div>
  );
}

function AgentRow({ logs, status, activeAgentName }: { logs: LogEntry[]; status: "running" | "done" | "stopped" | "error"; activeAgentName: string }) {
  const activeAgentIndex = ALL_SEVEN_AGENTS.findIndex(a => a.name === activeAgentName);
  
  return (
    <div className="glass border border-slate-800/40 rounded-xl p-4 shadow-md">
      <div className="flex flex-wrap items-center justify-center gap-4">
        {ALL_SEVEN_AGENTS.map((agent, idx) => {
          const isSystem = agent.name === "System";
          let isCompleted = false;
          let isActive = false;
          
          if (status === "done") {
            isCompleted = true;
          } else if (status === "error" || status === "stopped") {
            isCompleted = idx < activeAgentIndex;
          } else {
            if (isSystem) {
              isCompleted = false;
              isActive = false;
            } else {
              isCompleted = idx < activeAgentIndex;
              isActive = idx === activeAgentIndex;
            }
          }

          let stateClass = "bg-slate-950/50 text-slate-500 border-slate-900";
          if (isActive) {
            stateClass = "bg-slate-850 text-white ring-2 ring-cyan-500/50 shadow-lg shadow-cyan-500/10";
          } else if (isCompleted) {
            stateClass = "bg-emerald-500/5 text-emerald-450 border-emerald-500/20";
          }

          return (
            <div
              key={agent.name}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-semibold select-none relative transition-all duration-300 ${stateClass}`}
            >
              {isActive && (
                <span className="absolute -top-1 -right-1 flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-400"></span>
                </span>
              )}
              <span>{agent.emoji}</span>
              <span>{agent.name}</span>
              {isCompleted && (
                <span className="text-emerald-500 font-bold ml-1">✓</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BrowserPreview({ screenshotB64, historical }: { screenshotB64: string | null; historical: boolean }) {
  if (!screenshotB64) {
    return (
      <div className="glass border border-slate-800/40 rounded-2xl p-8 text-center min-h-[380px] flex flex-col justify-center items-center shadow-inner">
        <div className="w-full max-w-lg border border-slate-800 rounded-xl overflow-hidden bg-slate-950/30">
          <div className="bg-slate-900/80 px-4 py-2 border-b border-slate-800 flex items-center gap-2">
            <div className="flex gap-1.5">
              <span className="w-3 h-3 rounded-full bg-slate-700" />
              <span className="w-3 h-3 rounded-full bg-slate-700" />
              <span className="w-3 h-3 rounded-full bg-slate-700" />
            </div>
            <div className="flex-1 max-w-md mx-auto h-5 rounded-md bg-slate-950/50 border border-slate-800" />
          </div>
          <div className="p-16 flex flex-col items-center gap-3">
            <span className="text-4xl animate-pulse">📷</span>
            <p className="text-sm font-semibold text-slate-350">{historical ? "No browser screenshot available." : "Live browser screenshot captured when Explorer runs"}</p>
            <p className="text-xs text-slate-500 max-w-xs mx-auto">
              {historical ? "This completed analysis did not save a browser screenshot." : "Playwright will launch and visit the server. The home page preview will appear here."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="glass border border-slate-800/40 rounded-2xl shadow-xl overflow-hidden bg-slate-950/20">
      <div className="bg-slate-900/80 px-4 py-3 border-b border-slate-800 flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <span className="w-3 h-3 rounded-full bg-rose-500" />
            <span className="w-3 h-3 rounded-full bg-amber-500" />
            <span className="w-3 h-3 rounded-full bg-emerald-500" />
          </div>
          <div className="rounded-md bg-slate-950 px-4 py-1 text-xs text-slate-400 font-mono w-[260px] sm:w-[400px] truncate border border-slate-850">
            localhost:PORT — Live Playwright Preview
          </div>
        </div>
        <span className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-450 text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wider flex items-center gap-1.5 animate-pulse select-none shrink-0">
          <span className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-ping" />
          LIVE
        </span>
      </div>
      
      <div className="p-4 flex justify-center items-center bg-slate-950/45">
        <img
          src={`data:image/png;base64,${screenshotB64}`}
          alt="Playwright dynamic crawl screen preview"
          className="max-w-full rounded-lg shadow-inner max-h-[500px] object-contain border border-slate-800"
        />
      </div>
    </div>
  );
}

function EnhancedIssueCard({ issue }: { issue: IssueItem }) {
  const [open, setOpen] = useState(false);
  const severityColors = {
    critical: "bg-rose-500/10 border-rose-500/30 text-rose-400",
    high: "bg-rose-500/10 border-rose-500/20 text-rose-405",
    medium: "bg-amber-500/10 border-amber-500/30 text-amber-400",
    low: "bg-cyan-500/10 border-cyan-500/30 text-cyan-400",
    info: "bg-slate-500/10 border border-slate-700 text-slate-400",
  };

  return (
    <div className="glass border border-slate-850 rounded-xl overflow-hidden shadow-sm transition-all duration-300">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex flex-col md:flex-row items-start md:items-center justify-between p-4 bg-slate-900/30 hover:bg-slate-900/60 transition-colors gap-3 text-left animate-slide-up"
      >
        <div className="flex flex-wrap items-center gap-3 shrink-0">
          <span className="font-mono text-xs font-bold text-slate-500">{issue.issue_id}</span>
          <span className={`text-[9px] font-bold tracking-wider px-2 py-0.5 rounded border uppercase ${severityColors[issue.severity_level]}`}>
            {issue.severity_level}
          </span>
          <span className="font-mono text-xs text-cyan-400 whitespace-nowrap">{issue.file_name}{issue.line_number ? `:${issue.line_number}` : ""}</span>
          <VerdictBadge verdict={issue.review_verdict} />
        </div>
        <div className="flex items-center justify-between w-full md:flex-1 gap-4">
          <span className="text-slate-200 text-xs font-semibold tracking-wide">
            {issue.issue_title}
          </span>
          <span className="text-slate-500 text-[10px] shrink-0 font-mono ml-auto">
            {open ? "COLLAPSE ▲" : "EXPAND ▼"}
          </span>
        </div>
      </button>

      {open && (
        <div className="p-5 border-t border-slate-900 bg-slate-950/60 space-y-5 animate-slide-up">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="space-y-1">
              <span className="text-[10px] font-display font-semibold text-slate-550 uppercase tracking-wider block">
                Explanation
              </span>
              <p className="text-slate-300 text-xs leading-relaxed">
                {issue.explanation}
              </p>
            </div>
            <div className="space-y-1">
              <span className="text-[10px] font-display font-semibold text-amber-500 uppercase tracking-wider block">
                Estimated Impact
              </span>
              <p className="text-amber-400/90 text-xs leading-relaxed bg-amber-500/5 p-3 rounded-lg border border-amber-500/10">
                ⚠️ {issue.estimated_impact}
              </p>
            </div>
          </div>

          {issue.code_snippet && (
            <div className="space-y-1.5">
              <span className="text-[10px] font-display font-semibold text-slate-550 uppercase tracking-wider block">
                Unsafe Code Snippet
              </span>
              <pre className="bg-rose-950/10 border border-rose-900/20 text-rose-350 p-4 rounded-lg text-xs font-mono overflow-x-auto">
                {issue.code_snippet}
              </pre>
            </div>
          )}

          <div className="space-y-1.5">
            <span className="text-[10px] font-display font-semibold text-slate-550 uppercase tracking-wider block">
              Recommended Fix
            </span>
            <pre className="bg-emerald-950/10 border border-emerald-900/20 text-emerald-355 p-4 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap">
              {issue.recommended_fix}
            </pre>
          </div>

          {/* Reviewer Section */}
          <div className="border border-violet-500/30 bg-violet-950/5 rounded-xl p-4 space-y-4">
            <div className="flex flex-wrap items-center justify-between border-b border-violet-500/20 pb-2 gap-2">
              <div className="flex items-center gap-2">
                <span className="text-sm">🤖</span>
                <h4 className="font-display font-bold text-xs uppercase tracking-wider text-violet-400">
                  RepoGuardian Reviewer
                </h4>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <VerdictBadge verdict={issue.review_verdict} />
                <span className="text-slate-400 text-xs font-semibold">
                  Confidence: <span className="text-white">{issue.confidence_score}%</span>
                </span>
                <span className="text-slate-400 text-xs font-semibold">
                  Risk: <span className="text-rose-400 uppercase">{issue.risk_level}</span>
                </span>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="space-y-1">
                <span className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider block">
                  Why Valid
                </span>
                <p className="text-slate-350 text-xs leading-relaxed">
                  {issue.validity_explanation}
                </p>
              </div>
              <div className="space-y-1">
                <span className="text-[10px] font-display font-semibold text-amber-500 uppercase tracking-wider block">
                  Side Effects
                </span>
                <p className="text-amber-400/90 text-xs leading-relaxed">
                  {issue.potential_side_effects}
                </p>
              </div>
              <div className="space-y-1">
                <span className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider block">
                  Alternatives
                </span>
                <p className="text-slate-350 text-xs leading-relaxed">
                  {issue.alternative_approaches}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function isRenderableIssue(issue: Partial<IssueItem> & Record<string, any>): boolean {
  return Boolean(issue.issue_title || issue.error_type || issue.explanation || issue.error_description || issue.recommended_fix || issue.suggested_fix);
}

function normalizeIssue(issue: Bug | IssueItem): IssueItem {
  const raw = issue as Bug & Partial<IssueItem>;
  return {
    issue_id: raw.issue_id || raw.error_type || "Issue",
    issue_title: raw.issue_title || raw.error_type || "Issue detected",
    file_name: raw.file_name || raw.file || "Unknown file",
    line_number: raw.line_number ?? null,
    severity_level: raw.severity_level || (raw.severity === "critical" ? "critical" : raw.severity === "info" ? "info" : "medium"),
    explanation: raw.explanation || raw.error_description || "No description was provided.",
    recommended_fix: raw.recommended_fix || raw.suggested_fix || "No recommendation was provided.",
    estimated_impact: raw.estimated_impact || "Impact not provided.",
    code_snippet: raw.code_snippet,
    confidence_score: raw.confidence_score ?? null,
    risk_level: raw.risk_level ?? null,
    review_verdict: raw.review_verdict ?? null,
    validity_explanation: raw.validity_explanation || "",
    potential_side_effects: raw.potential_side_effects || "",
    alternative_approaches: raw.alternative_approaches || "",
  };
}

type SecCheckTab = "secrets" | "data_flow" | "predeploy" | "deep" | "attacker";

function SecurityPanel({ report, historical }: { report: SecurityReport | null; historical: boolean }) {
  const [activeCheck, setActiveCheck] = useState<SecCheckTab>("secrets");

  if (!report) {
    return (
      <div className="glass border border-slate-800/40 rounded-2xl p-16 text-center shadow-md">
        <p className="text-slate-500 text-sm font-mono">
          {historical ? "No security findings available." : "Security scans are compiling. Running 5 layers of checks..."}
        </p>
      </div>
    );
  }

  const emptyCheck = { findings: [], summary: "No issues found in this check." };
  const check_1_secrets = report.check_1_secrets || emptyCheck;
  const check_2_data_flow = report.check_2_data_flow || emptyCheck;
  const check_3_predeploy = report.check_3_predeploy || { ...emptyCheck, deploy_ready: true };
  const check_4_deep = report.check_4_deep || emptyCheck;
  const check_5_attacker = report.check_5_attacker || emptyCheck;

  const deployReady = check_3_predeploy.deploy_ready !== false;

  const checks = [
    { id: "secrets" as SecCheckTab, label: "🔑 Secret Leak", data: check_1_secrets },
    { id: "data_flow" as SecCheckTab, label: "👤 Data Flow", data: check_2_data_flow },
    { id: "predeploy" as SecCheckTab, label: "🚀 Pre-Deploy", data: check_3_predeploy },
    { id: "deep" as SecCheckTab, label: "🔬 Deep Logic", data: check_4_deep },
    { id: "attacker" as SecCheckTab, label: "💀 Attacker View", data: check_5_attacker }
  ].map((check) => ({ ...check, findings: (check.data.findings || []).filter(isRenderableSecurityFinding).map(normalizeSecurityFinding), count: (check.data.findings || []).filter(isRenderableSecurityFinding).length }));

  const currentCheck = checks.find(c => c.id === activeCheck)!;
  const visibleFindings = checks.reduce((total, check) => total + check.count, 0);
  const visibleCritical = checks.reduce((total, check) => total + check.findings.filter((finding) => finding.severity === "critical").length, 0);

  return (
    <div className="space-y-6">
      {/* Summary Strip */}
      <div className="glass border border-slate-800/60 rounded-2xl p-6 flex flex-col md:flex-row items-center justify-between gap-4 shadow-xl">
        <div>
          <h3 className="font-display font-bold text-base text-white tracking-wide">
            5-Layer Security Audit
          </h3>
          <p className="text-slate-450 text-xs mt-0.5">
            Based on Gitleaks · Bearer · ECC · Trail of Bits methodologies
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs font-mono font-bold px-3 py-1 rounded-full">
            🚨 {visibleCritical} Critical
          </span>
          <span className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-mono font-bold px-3 py-1 rounded-full">
            ⚠️ {visibleFindings} Total
          </span>
          {deployReady ? (
            <span className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-450 text-xs font-mono font-bold px-3 py-1 rounded-full">
              ✅ Deploy Ready
            </span>
          ) : (
            <span className="bg-rose-500/10 border border-rose-500/20 text-rose-450 text-xs font-mono font-bold px-3 py-1 rounded-full animate-pulse">
              ❌ Not Deploy Ready
            </span>
          )}
        </div>
      </div>

      {/* Sub-tabs */}
      <div className="flex flex-wrap gap-1 border-b border-slate-800/80 pb-px">
        {checks.map(chk => (
          <button
            key={chk.id}
            onClick={() => setActiveCheck(chk.id)}
            className={`px-4 py-2 text-xs font-semibold tracking-wide transition-all border-b-2 -mb-px flex items-center gap-2 ${
              activeCheck === chk.id
                ? "border-cyan-500 text-cyan-400"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            <span>{chk.label}</span>
            {chk.count > 0 && (
              <span className="bg-rose-500/15 border border-rose-500/25 text-rose-400 text-[10px] px-1.5 py-0.2 rounded-full font-mono font-bold">
                {chk.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Finding List */}
      <div className="space-y-4 animate-slide-up">
        {currentCheck.count === 0 ? (
          <div className="glass border border-slate-850 rounded-xl p-8 text-center space-y-2">
            <div className="text-3xl text-emerald-450">✨</div>
            <h4 className="font-display font-bold text-slate-200 text-sm">
              No issues found in this check
            </h4>
            <p className="text-slate-500 text-xs max-w-sm mx-auto">
              {currentCheck.data.summary || "Security policies satisfied."}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {currentCheck.findings.map((f, fidx) => (
              <SecurityFindingCard key={fidx} finding={f} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SecurityFindingCard({ finding }: { finding: SecurityFinding }) {
  const [open, setOpen] = useState(false);
  const severityColors = {
    critical: "bg-rose-500/10 border-rose-500/30 text-rose-450",
    high: "bg-rose-500/10 border-rose-500/20 text-rose-400",
    medium: "bg-amber-500/10 border-amber-500/30 text-amber-400",
    low: "bg-cyan-500/10 border-cyan-500/30 text-cyan-400",
  };

  const scenario = finding.exploit_scenario || finding.attack_scenario || finding.damage_potential || (finding as SecurityFinding & { impact?: string }).impact;

  return (
    <div className="glass border border-slate-850 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex flex-col md:flex-row items-start md:items-center justify-between p-4 bg-slate-900/30 hover:bg-slate-900/60 transition-colors gap-3 text-left"
      >
        <div className="flex flex-wrap items-center gap-3 shrink-0">
          <span className="font-mono text-xs font-semibold text-slate-500">{finding.check_id}</span>
          <span className={`text-[9px] font-bold tracking-wider px-2 py-0.5 rounded border uppercase ${severityColors[finding.severity]}`}>
            {finding.severity}
          </span>
          {finding.file_name && (
            <span className="font-mono text-xs text-cyan-400">{finding.file_name}</span>
          )}
        </div>
        <div className="flex items-center justify-between w-full md:flex-1 gap-4">
          <span className="text-slate-200 text-xs font-semibold">
            {finding.title}
          </span>
          <span className="text-slate-500 text-[10px] font-mono shrink-0 ml-auto">
            {open ? "COLLAPSE ▲" : "EXPAND ▼"}
          </span>
        </div>
      </button>

      {open && (
        <div className="p-5 border-t border-slate-900 bg-slate-950/60 space-y-4 animate-slide-up">
          <div className="space-y-1">
            <span className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider block">
              Description
            </span>
            <p className="text-slate-350 text-xs leading-relaxed">
              {finding.description}
            </p>
          </div>

          {scenario && (
            <div className="space-y-1.5">
              <span className="text-[10px] font-display font-semibold text-rose-400 uppercase tracking-wider block">
                Exploit Scenario / Damage Potential
              </span>
              <pre className="bg-rose-950/10 border border-rose-900/20 text-rose-350 p-4 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap">
                {scenario}
              </pre>
            </div>
          )}

          <div className="space-y-1.5">
            <span className="text-[10px] font-display font-semibold text-emerald-450 uppercase tracking-wider block">
              Remediation / Fix
            </span>
            <pre className="bg-emerald-950/10 border border-emerald-900/20 text-emerald-355 p-4 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap">
              {finding.fix}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function isRenderableSecurityFinding(finding: Partial<SecurityFinding> & Record<string, any>): boolean {
  return Boolean(finding.title || finding.vulnerability || finding.description || finding.recommendation || finding.fix);
}

function normalizeSecurityFinding(finding: SecurityFinding & Record<string, any>): SecurityFinding {
  return {
    check_id: finding.check_id || "Security finding",
    title: finding.title || finding.vulnerability || finding.name || "Security finding",
    file_name: finding.file_name || finding.file,
    severity: finding.severity || "medium",
    description: finding.description || finding.details || "No description was provided.",
    fix: finding.fix || finding.recommendation || "No recommendation was provided.",
    attack_scenario: finding.attack_scenario,
    exploit_scenario: finding.exploit_scenario,
    damage_potential: finding.damage_potential,
  };
}

function MarketPanel({ report, historical }: { report: MarketReport | null; historical: boolean }) {
  console.debug("[analysis] market tab render", { hasReport: Boolean(report), historical });
  if (!report) {
    return (
      <div className="glass border border-slate-800/40 rounded-2xl p-16 text-center shadow-md">
        <p className="text-slate-500 text-sm font-mono">
          {historical ? "No market analysis available." : "Generating market strategist reports. Conducting competitive landscape analysis..."}
        </p>
      </div>
    );
  }

  const {
    project_summary,
    one_line_pitch,
    viability_score,
    viability_reason,
    market_exists,
    market_size,
    target_audience,
    competitors,
    market_gap,
    unique_differentiators,
    startup_roadmap,
    risks,
    recommended_next_feature,
    investor_appeal
  } = report;

  return (
    <div className="space-y-6">
      {/* Hero Card */}
      <div className="glass border-glow rounded-2xl p-6 shadow-xl space-y-6">
        <div className="flex flex-col md:flex-row items-center md:items-start justify-between gap-6">
          <div className="space-y-4 flex-1">
            <h3 className="text-lg md:text-xl font-display font-bold text-white tracking-wide">
              {project_summary}
            </h3>
            <div className="glass px-4 py-2.5 rounded-lg border border-cyan-500/20 text-cyan-400 text-xs italic inline-block">
              &ldquo;{one_line_pitch}&rdquo;
            </div>
          </div>
          
          <div className="flex flex-col items-center md:items-end justify-center shrink-0 text-center md:text-right max-w-xs gap-3">
            <ScoreRing score={viability_score} label="Viability Rating" />
            <p className="text-slate-400 text-[10px] leading-relaxed">
              {viability_reason}
            </p>
          </div>
        </div>

        {/* Three Columns Info */}
        <div className="grid grid-cols-1 md:grid-cols-3 border-t border-slate-800 pt-4 gap-4">
          <div>
            <span className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider block">
              Market Size
            </span>
            <span className="text-sm font-bold text-white block mt-0.5">
              {market_size}
            </span>
          </div>
          <div>
            <span className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider block">
              Paying Market Exists
            </span>
            <span className="text-sm font-bold text-white block mt-0.5">
              {market_exists ? "Yes, customer demand identified" : "Uncertain / Niche audience"}
            </span>
          </div>
          <div>
            <span className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider block">
              Investor Appeal
            </span>
            <span className="text-xs font-medium text-slate-350 block mt-0.5">
              {investor_appeal}
            </span>
          </div>
        </div>
      </div>

      {/* Grid Layout for audience & differentiators */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Target Audience */}
        <div className="glass border border-slate-800/40 rounded-2xl p-6 shadow-md space-y-4">
          <h3 className="font-display font-bold text-sm text-white flex items-center gap-2 border-b border-slate-850 pb-2 select-none">
            🎯 Target Audience
          </h3>
          <div className="divide-y divide-slate-850">
            {target_audience?.map((ta, idx) => (
              <div key={idx} className="py-3 first:pt-0 last:pb-0 flex items-center justify-between gap-4">
                <div className="space-y-0.5">
                  <span className="text-xs font-bold text-white block">{ta.segment}</span>
                  <span className="text-slate-450 text-[11px] block">{ta.pain_point}</span>
                </div>
                <span className="bg-slate-900 border border-slate-800 text-slate-400 text-[10px] font-mono font-bold px-2 py-0.5 rounded-full shrink-0">
                  {ta.size}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Unique Differentiators */}
        <div className="glass border border-slate-800/40 rounded-2xl p-6 shadow-md space-y-4">
          <h3 className="font-display font-bold text-sm text-white flex items-center gap-2 border-b border-slate-850 pb-2 select-none">
            🚀 What Makes You Unique
          </h3>
          <p className="text-slate-405 text-xs leading-relaxed">
            {market_gap}
          </p>
          <div className="space-y-2">
            {unique_differentiators?.map((diff, idx) => (
              <div key={idx} className="flex items-start gap-2 text-xs">
                <span className="text-cyan-450 select-none mt-0.5">✦</span>
                <span className="text-slate-300 leading-normal">{diff}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Competitor Analysis */}
      <div className="glass border border-slate-800/40 rounded-2xl p-6 shadow-md space-y-4">
        <h3 className="font-display font-bold text-sm text-white flex items-center gap-2 border-b border-slate-850 pb-2 select-none">
          ⚔️ Competitor Analysis
        </h3>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {competitors?.map((comp, idx) => (
            <div key={idx} className="bg-slate-950/30 border border-slate-850 rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between gap-2 border-b border-slate-855 pb-1.5">
                <div>
                  <span className="text-xs font-bold text-white block">{comp.name}</span>
                  <span className="text-[10px] text-slate-450 block">{comp.what_they_do}</span>
                </div>
                <span className="bg-slate-900 border border-slate-800 text-slate-400 text-[9px] font-mono px-2 py-0.5 rounded-full select-none">
                  {comp.pricing || "Free"}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-0.5">
                  <span className="text-[9px] font-display font-bold text-rose-450 uppercase tracking-wider block">
                    Their Weakness
                  </span>
                  <p className="text-slate-400 text-[10px] leading-relaxed">
                    {comp.their_weakness}
                  </p>
                </div>
                <div className="space-y-0.5">
                  <span className="text-[9px] font-display font-bold text-emerald-450 uppercase tracking-wider block">
                    Your Advantage
                  </span>
                  <p className="text-slate-400 text-[10px] leading-relaxed">
                    {comp.your_advantage}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Startup Roadmap */}
      <div className="glass border border-slate-800/40 rounded-2xl p-6 shadow-md space-y-6">
        <h3 className="font-display font-bold text-sm text-white flex items-center gap-2 border-b border-slate-850 pb-2 select-none">
          🗺️ Startup Roadmap
        </h3>
        
        <div className="relative pl-6 border-l border-slate-800 space-y-6 ml-2 py-2">
          {startup_roadmap?.map((step, idx) => (
            <div key={idx} className="relative space-y-1.5 animate-slide-up">
              <div className="absolute -left-[31px] top-0.5 flex items-center justify-center w-[10px] h-[10px] rounded-full bg-cyan-400 ring-4 ring-[#020817]" />
              
              <div className="flex flex-wrap items-center gap-2">
                <span className="bg-slate-900 border border-slate-800 text-cyan-400 text-[10px] font-mono font-bold px-2 py-0.5 rounded-full uppercase">
                  Phase {step.step}: {step.phase}
                </span>
                <span className="text-slate-500 font-mono text-[10px]">
                  ({step.timeline})
                </span>
              </div>
              <p className="text-slate-200 text-xs font-semibold">
                {step.action}
              </p>
              <div className="text-[10px] text-cyan-400/90 font-mono">
                KPI: <span className="text-slate-405">{step.metric}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Risks */}
      <div className="glass border border-slate-800/40 rounded-2xl p-6 shadow-md space-y-5">
        <h3 className="font-display font-bold text-sm text-white flex items-center gap-2 border-b border-slate-850 pb-2 select-none">
          ⚠️ Key Risks & Mitigations
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {risks?.map((risk, idx) => (
            <div key={idx} className="bg-slate-950/20 border border-slate-850 rounded-lg p-3 space-y-1">
              <div className="text-xs text-rose-450 font-semibold">
                Risk: {risk.risk}
              </div>
              <div className="text-[11px] text-emerald-450 leading-relaxed">
                Mitigation: {risk.mitigation}
              </div>
            </div>
          ))}
        </div>
        
        <div className="bg-cyan-950/10 border border-cyan-500/20 rounded-xl p-4 mt-2">
          <div className="text-xs font-bold text-cyan-400 uppercase tracking-wider mb-1.5 flex items-center gap-1.5 select-none">
            <span>💡</span> Recommended Next Feature
          </div>
          <p className="text-slate-200 text-xs leading-normal">
            {recommended_next_feature}
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Legacy panel components ──────────────────────────────────────────────────

function BugCard({ bug }: { bug: Bug }) {
  const [open, setOpen] = useState(false);
  const severityColors = {
    critical: "bg-rose-500/10 border-rose-500/30 text-rose-400",
    warning: "bg-amber-500/10 border-amber-500/30 text-amber-400",
    info: "bg-cyan-500/10 border-cyan-500/30 text-cyan-400",
  };

  return (
    <div className="glass border border-slate-850 rounded-xl overflow-hidden shadow-sm transition-all duration-300">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex flex-col sm:flex-row items-start sm:items-center justify-between p-4 bg-slate-900/30 hover:bg-slate-900/60 transition-colors gap-3 text-left"
      >
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-[9px] font-bold tracking-wider px-2 py-0.5 rounded border uppercase ${severityColors[bug.severity]}`}>
            {bug.severity}
          </span>
          <span className="font-mono text-xs text-cyan-400 whitespace-nowrap">{bug.file}</span>
          {bug.line_number && (
            <span className="text-slate-600 text-[10px] font-mono shrink-0">:{bug.line_number}</span>
          )}
        </div>
        <div className="flex items-center gap-2 w-full sm:flex-1">
          <span className="text-slate-300 text-xs font-medium flex-1">
            {bug.error_description}
          </span>
          <span className="text-slate-500 text-[10px] shrink-0 font-mono ml-auto">
            {open ? "COLLAPSE ▲" : "EXPAND ▼"}
          </span>
        </div>
      </button>

      {open && (
        <div className="p-5 border-t border-slate-900 bg-slate-950/60 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <p className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider mb-1">
                Category
              </p>
              <p className="text-slate-200 text-xs font-mono bg-slate-900 px-3 py-1 rounded border border-slate-800 inline-block">
                {bug.error_type}
              </p>
            </div>
          </div>

          {bug.code_snippet && (
            <div className="space-y-1.5">
              <p className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider">
                Unsafe Snippet
              </p>
              <pre className="bg-rose-950/10 border border-rose-900/20 text-rose-300 p-3.5 rounded-lg text-xs font-mono overflow-x-auto">
                {bug.code_snippet}
              </pre>
            </div>
          )}

          <div className="space-y-1.5">
            <p className="text-[10px] font-display font-semibold text-slate-500 uppercase tracking-wider">
              Recommended Fix
            </p>
            <pre className="bg-emerald-950/10 border border-emerald-900/20 text-emerald-300 p-3.5 rounded-lg text-xs font-mono overflow-x-auto whitespace-pre-wrap">
              {bug.suggested_fix}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

function DiffCollapse({ diff }: { diff: Diff }) {
  const [open, setOpen] = useState(false);

  if (!diff.success) {
    return (
      <div className="glass border border-amber-500/20 rounded-xl p-5 bg-slate-950/50 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-amber-400 text-xs font-bold">Manual remediation required</span>
          <span className="text-cyan-400 text-xs font-mono">{diff.file}</span>
        </div>
        <p className="text-slate-300 text-sm">{diff.bug?.error_type || "Issue detected"}</p>
        <p className="text-slate-400 text-xs leading-relaxed">{diff.bug?.error_description || diff.error || "An automatic patch could not be generated."}</p>
        <div className="border-t border-slate-800 pt-3">
          <span className="text-[10px] text-emerald-400 uppercase tracking-wider font-bold">Recommended remediation</span>
          <p className="text-emerald-300 text-xs leading-relaxed mt-1">{diff.bug?.suggested_fix || "Review the issue and apply the recommended change manually."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="glass border border-slate-850 rounded-xl overflow-hidden shadow-sm">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between p-4 bg-slate-900/30 hover:bg-slate-900/60 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="text-xs text-emerald-400 font-bold tracking-wider uppercase bg-emerald-500/10 border border-emerald-500/20 px-2 py-0.5 rounded">
            PR Fix Available
          </span>
          <span className="font-mono text-xs text-cyan-400 truncate max-w-[200px] sm:max-w-md">
            {diff.file}
          </span>
        </div>
        <span className="text-slate-500 text-[10px] font-mono font-semibold">
          {open ? "HIDE DIFF ▲" : "SHOW DIFF ▼"}
        </span>
      </button>

      {open && (
        <div className="border-t border-slate-900/80 bg-slate-950 font-mono overflow-hidden">
          <ReactDiffViewer
            oldValue={diff.original}
            newValue={diff.fixed}
            splitView={true}
            useDarkTheme={true}
            leftTitle="Original Source"
            rightTitle="Proposed Fix"
          />
        </div>
      )}
    </div>
  );
}

function ArchitecturePanel({ result, historical }: { result: JobResult; historical: boolean }) {
  const architecture = result?.architecture;
  console.debug("[analysis] architecture tab render", {
    hasArchitecture: Boolean(architecture),
    staticIssues: architecture?.static_issues?.length ?? 0,
    historical,
  });
  if (!architecture) {
    return (
      <div className="glass border border-slate-800/40 rounded-2xl p-16 text-center shadow-md">
        <h3 className="font-display font-bold text-slate-200 text-base">No Architecture Analysis</h3>
        <p className="text-slate-500 text-xs mt-2">Architecture data was not generated for this repository.</p>
      </div>
    );
  }

  const static_issues = Array.isArray(architecture.static_issues) ? architecture.static_issues : [];
  const ai_analysis = architecture.ai_analysis || "No AI architecture report is available.";
  const summary = architecture.summary || {};
  const score = typeof architecture.score === "number" ? architecture.score : 0;

  const severityGlows = {
    critical: "bg-rose-500/10 border-rose-500/20 text-rose-405",
    warning: "bg-amber-500/10 border-amber-500/20 text-amber-450",
    info: "bg-cyan-500/10 border-cyan-500/20 text-cyan-400",
  };

  const radius = 35;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;
  const scoreColor = score >= 80 ? "text-emerald-450" : score >= 50 ? "text-amber-450" : "text-rose-450";
  const strokeColor = score >= 80 ? "#10b981" : score >= 50 ? "#f59e0b" : "#f43f5e";

  return (
    <div className="space-y-6">
      <div className="glass border border-slate-800/60 bg-slate-950/20 rounded-2xl p-6 flex flex-col sm:flex-row items-center gap-6 shadow-xl">
        <div className="relative flex items-center justify-center shrink-0 w-24 h-24">
          <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="transparent"
              stroke="#1e293b"
              strokeWidth="8"
            />
            <circle
              cx="50"
              cy="50"
              r={radius}
              fill="transparent"
              stroke={strokeColor}
              strokeWidth="8"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              strokeLinecap="round"
              className="transition-all duration-1000 ease-out score-ring-path"
            />
          </svg>
          <div className="absolute flex flex-col items-center justify-center text-center">
            <span className={`text-xl font-mono font-black ${scoreColor}`}>
              {score}
            </span>
            <span className="text-[8px] text-slate-500 font-bold uppercase tracking-wider">Score</span>
          </div>
        </div>
        <div className="flex-1 text-center sm:text-left space-y-1">
          <h3 className="font-display font-bold text-base text-white tracking-wide">
            Architecture Health Score
          </h3>
          <p className="text-slate-400 text-xs leading-relaxed max-w-xl">
            {score >= 80 ? (
              <span className="text-emerald-450 font-bold">Excellent Health: </span>
            ) : score >= 50 ? (
              <span className="text-amber-450 font-bold">Needs Improvement: </span>
            ) : (
              <span className="text-rose-455 font-bold">Critical Vulnerabilities: </span>
            )}
            This metric summarizes repository structure, security variables hygiene, and performance patterns identified in your static project files.
          </p>
          <div className="flex flex-wrap justify-center sm:justify-start gap-2 pt-2">
            <span className={`text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${severityGlows.critical}`}>
              🚨 {summary.critical ?? 0} Critical
            </span>
            <span className={`text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${severityGlows.warning}`}>
              ⚠️ {summary.warnings ?? 0} Warnings
            </span>
            <span className={`text-[10px] font-bold uppercase tracking-wider px-3 py-1 rounded-full border ${severityGlows.info}`}>
              ℹ️ {summary.info ?? 0} Notes
            </span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-3">
          <h4 className="font-display font-bold text-xs uppercase tracking-widest text-slate-400 mb-2">
            Static Lint Issues ({static_issues.length})
          </h4>
          {static_issues.length === 0 ? (
            <p className="text-slate-600 text-xs italic">No critical configuration risks or security variables detected in standard files.</p>
          ) : (
            static_issues.map((issue, idx) => (
              <div
                key={idx}
                className={`p-4 rounded-xl border ${
                  issue.severity === "critical" ? "bg-rose-950/10 border-rose-900/30" : "bg-slate-900/40 border-slate-800/80"
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs font-bold ${issue.severity === "critical" ? "text-rose-405" : "text-amber-405"}`}>
                    {issue.title}
                  </span>
                  {issue.file && (
                    <span className="font-mono text-[9px] text-cyan-400 px-2 py-0.5 bg-slate-950 rounded border border-slate-800">
                      {issue.file}{issue.line ? `:${issue.line}` : ""}
                    </span>
                  )}
                </div>
                <p className="text-slate-400 text-xs leading-relaxed mb-2">
                  {issue.description}
                </p>
                <div className="text-slate-205 text-xs font-medium bg-slate-900/50 p-2.5 rounded-lg border border-slate-800/60">
                  💡 {issue.suggestion}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="space-y-3">
          <h4 className="font-display font-bold text-xs uppercase tracking-widest text-slate-400 mb-2">
            AI Architectural Report
          </h4>
          <div className="glass border border-slate-800/60 rounded-xl p-5 shadow-md">
            <div className="text-xs text-purple-400 font-display font-bold uppercase tracking-wider mb-3 flex items-center gap-1.5 select-none">
              <span>🏗️</span> Gemini 1.5 Flash Architect Review
            </div>
            <div className="text-slate-300 text-xs leading-relaxed whitespace-pre-wrap font-sans space-y-4">
              {ai_analysis}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
