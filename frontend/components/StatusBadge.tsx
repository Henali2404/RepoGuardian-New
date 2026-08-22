"use client";

type Status = "running" | "done" | "stopped" | "error" | "pending";

interface StatusBadgeProps {
  status: Status;
  className?: string;
}

const CONFIG: Record<Status, { dot: string; text: string; bg: string; border: string; label: string }> = {
  running: {
    dot: "bg-cyan-400 animate-pulse shadow-[0_0_8px_rgba(34,211,238,0.5)]",
    text: "text-cyan-400",
    bg: "bg-cyan-500/10",
    border: "border-cyan-500/30",
    label: "Running...",
  },
  done: {
    dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.5)]",
    text: "text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/30",
    label: "Complete",
  },
  stopped: {
    dot: "bg-orange-400",
    text: "text-orange-400",
    bg: "bg-orange-500/10",
    border: "border-orange-500/30",
    label: "Stopped",
  },
  error: {
    dot: "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.5)]",
    text: "text-rose-400",
    bg: "bg-rose-500/10",
    border: "border-rose-500/30",
    label: "Failed",
  },
  pending: {
    dot: "bg-slate-500",
    text: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-slate-500/30",
    label: "Pending",
  },
};

export default function StatusBadge({ status, className = "" }: StatusBadgeProps) {
  const c = CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-2 px-3 py-1 rounded-full border text-xs font-semibold uppercase tracking-wider backdrop-blur-md
        ${c.bg} ${c.border} ${c.text} ${className}`}
    >
      <span className={`w-2 h-2 rounded-full shrink-0 ${c.dot}`} />
      {c.label}
    </span>
  );
}
