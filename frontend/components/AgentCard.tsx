"use client";

interface AgentCardProps {
  name: string;
  emoji: string;
  description: string;
  active?: boolean;
  done?: boolean;
  lastMessage?: string;
}

const AGENT_COLORS: Record<string, { border: string; bg: string; text: string; glow: string }> = {
  Scanner: {
    border: "border-cyan-500/30 group-hover:border-cyan-500/50",
    bg: "bg-cyan-500/5",
    text: "text-cyan-400",
    glow: "shadow-[0_0_15px_rgba(6,182,212,0.15)]",
  },
  Explorer: {
    border: "border-emerald-500/30 group-hover:border-emerald-500/50",
    bg: "bg-emerald-500/5",
    text: "text-emerald-400",
    glow: "shadow-[0_0_15px_rgba(16,185,129,0.15)]",
  },
  Auditor: {
    border: "border-amber-500/30 group-hover:border-amber-500/50",
    bg: "bg-amber-500/5",
    text: "text-amber-400",
    glow: "shadow-[0_0_15px_rgba(245,158,11,0.15)]",
  },
  Architect: {
    border: "border-violet-500/30 group-hover:border-violet-500/50",
    bg: "bg-violet-500/5",
    text: "text-violet-400",
    glow: "shadow-[0_0_15px_rgba(124,58,237,0.15)]",
  },
  Executor: {
    border: "border-rose-500/30 group-hover:border-rose-500/50",
    bg: "bg-rose-500/5",
    text: "text-rose-400",
    glow: "shadow-[0_0_15px_rgba(244,63,94,0.15)]",
  },
  System: {
    border: "border-slate-500/30 group-hover:border-slate-500/50",
    bg: "bg-slate-500/5",
    text: "text-slate-400",
    glow: "shadow-[0_0_15px_rgba(100,116,139,0.15)]",
  },
};

export default function AgentCard({
  name,
  emoji,
  description,
  active = false,
  done = false,
  lastMessage,
}: AgentCardProps) {
  const c = AGENT_COLORS[name] || AGENT_COLORS.System;

  return (
    <div className="perspective-3d group">
      <div
        className={`preserve-3d card-3d-rotate glass-panel border rounded-2xl p-5 transition-all duration-300 min-h-[140px] flex flex-col justify-between ${
          active
            ? `border-${name === "Scanner" ? "cyan" : name === "Explorer" ? "emerald" : name === "Auditor" ? "amber" : name === "Architect" ? "violet" : "rose"}-500/60 ${c.bg} ${c.glow}`
            : done
            ? "border-emerald-500/40 bg-emerald-950/10 shadow-[0_0_10px_rgba(16,185,129,0.05)]"
            : "border-slate-800 bg-slate-950/40"
        }`}
      >
        <div>
          {/* Header row */}
          <div className="flex items-start justify-between mb-3">
            <div className="flex items-center gap-3">
              <span className="text-3xl filter drop-shadow-[0_2px_8px_rgba(255,255,255,0.15)]">{emoji}</span>
              <div>
                <p className={`font-display font-bold text-base tracking-wide ${active ? c.text : done ? "text-emerald-400" : "text-slate-300"}`}>
                  {name}
                </p>
                <p className="text-slate-500 text-xs mt-0.5 font-medium leading-relaxed">{description}</p>
              </div>
            </div>
            {active && (
              <span className={`flex items-center gap-1.5 text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full border border-current ${c.text} animate-pulse`}>
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                ACTIVE
              </span>
            )}
            {done && !active && (
              <span className="text-emerald-400 text-sm font-bold animate-fade-in">✓</span>
            )}
          </div>
        </div>

        {/* Last message (console/log style) */}
        {lastMessage ? (
          <div className="mt-3 bg-slate-950/80 border border-slate-800/60 rounded-lg p-2 font-mono text-[10px] text-slate-400 truncate max-w-full">
            <span className="text-slate-600 mr-1">$</span> {lastMessage}
          </div>
        ) : (
          <div className="h-4" /> // Spacing
        )}
      </div>
    </div>
  );
}
