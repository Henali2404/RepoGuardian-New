"use client";

interface RepoInputProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  loading?: boolean;
  error?: string;
}

export default function RepoInput({
  value,
  onChange,
  onSubmit,
  loading = false,
  error,
}: RepoInputProps) {
  return (
    <div className="w-full max-w-2xl mx-auto">
      <label className="block text-[10px] font-display font-semibold text-slate-500 uppercase tracking-[0.2em] mb-2.5 text-center sm:text-left">
        GitHub Repository URL
      </label>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1 group">
          {/* Glowing border underlay */}
          <div className="absolute -inset-px bg-gradient-to-r from-cyan-500 to-violet-500 rounded-xl opacity-20 group-hover:opacity-40 transition-opacity blur-[2px]" />
          
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-500 text-base pointer-events-none select-none">
            ⚡
          </span>
          <input
            type="url"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !loading && onSubmit()}
            placeholder="https://github.com/username/repository"
            className={`w-full pl-11 pr-4 py-4 bg-slate-900/60 rounded-xl text-slate-200 text-sm placeholder-slate-600
              border transition-all focus:outline-none backdrop-blur-md relative z-10
              ${error ? "border-rose-500/50 focus:border-rose-500" : "border-slate-800 focus:border-cyan-500/50"}`}
          />
        </div>

        <button
          onClick={onSubmit}
          disabled={!value.trim() || loading}
          className="relative group shrink-0 active:scale-95 transition-transform duration-100 z-10"
        >
          {/* Glow backdrop for button */}
          <div className="absolute -inset-0.5 bg-gradient-to-r from-cyan-500 to-violet-500 rounded-xl opacity-40 group-hover:opacity-75 blur-[4px] transition-all duration-300" />
          
          <div className="relative bg-gradient-to-r from-cyan-500 to-cyan-400 text-slate-950 font-bold px-8 py-4 rounded-xl text-sm
            transition-all flex items-center justify-center gap-2 shadow-lg shadow-cyan-500/20 group-hover:shadow-cyan-500/35">
            {loading ? (
              <>
                <svg className="animate-spin w-4 h-4 text-slate-950" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>Analyzing...</span>
              </>
            ) : (
              <>
                <span>Analyze Repository</span>
                <span className="text-xs">→</span>
              </>
            )}
          </div>
        </button>
      </div>

      {error ? (
        <p className="mt-3 text-rose-400 text-xs font-semibold animate-shake text-center sm:text-left">{error}</p>
      ) : (
        <p className="mt-3 text-slate-500 text-[10px] leading-relaxed text-center sm:text-left">
          Supports public GitHub repositories. Use standard URL paths (e.g., <code className="text-slate-400">https://github.com/facebook/react</code>).
        </p>
      )}
    </div>
  );
}
