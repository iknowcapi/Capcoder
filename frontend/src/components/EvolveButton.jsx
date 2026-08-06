import React, { useState } from "react";
import { Zap } from "lucide-react";

const STACK_HINTS = [
  { label: "Python + FastAPI", value: "python-fastapi" },
  { label: "React + Vite", value: "node-vite" },
  { label: "Rust", value: "rust" },
  { label: "Go", value: "go" },
  { label: "WebGL / HTML", value: "webgl" },
];

export const EvolveButton = ({ onEvolve, busy, currentStage }) => {
  const [target, setTarget] = useState("");
  const [stackHint, setStackHint] = useState("");

  const trigger = () => {
    const t = target.trim();
    if (!t) return;
    const full = stackHint ? `${t}\n\nStack: ${stackHint}` : t;
    onEvolve(full);
  };

  return (
    <section
      className="panel p-6 sm:p-8 relative"
      data-testid="evolve-panel"
      style={{ borderColor: "rgba(57,255,20,0.5)" }}
    >
      <div className="flex items-center gap-2 text-neon_cyan neon-cyan label-xs mb-6">
        <span>=== [ CAPCODE :: HUMAN → TEACHER → ARTIST → PRODUCT ] ===</span>
      </div>

      <div className="space-y-5 font-mono">
        <div>
          <label className="label-xs text-phosphor2 block mb-2" htmlFor="target-prompt">
            {"> describe the app you want built"}
          </label>
          <textarea
            id="target-prompt"
            data-testid="target-prompt"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            disabled={busy}
            rows={4}
            placeholder="e.g.  a react app that shows a live BTC price ticker with a spark line chart"
            className="w-full bg-black border border-phosphor/40 focus:border-phosphor text-phosphor px-3 py-2 font-mono text-sm resize-y disabled:opacity-30 outline-none"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className="label-xs text-phosphor3">stack (optional):</span>
          <button
            data-testid="stack-hint-auto"
            disabled={busy}
            onClick={() => setStackHint("")}
            className={`border px-2 py-1 text-[11px] font-mono transition-colors ${
              stackHint === ""
                ? "border-phosphor bg-phosphor/15 text-phosphor neon-text"
                : "border-phosphor/40 text-phosphor2 hover:border-phosphor"
            } disabled:opacity-30`}
          >
            auto-detect
          </button>
          {STACK_HINTS.map((s) => (
            <button
              key={s.value}
              data-testid={`stack-hint-${s.value}`}
              disabled={busy}
              onClick={() => setStackHint(s.value)}
              className={`border px-2 py-1 text-[11px] font-mono transition-colors ${
                stackHint === s.value
                  ? "border-phosphor bg-phosphor/15 text-phosphor neon-text"
                  : "border-phosphor/40 text-phosphor2 hover:border-phosphor"
              } disabled:opacity-30`}
            >
              {s.label}
            </button>
          ))}
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pt-2 border-t border-phosphor/20">
          <p className="text-phosphor2 text-[11px] sm:text-xs leading-relaxed max-w-[560px]">
            <span className="text-neon_cyan">TEACHER</span> (rigid, strict, learns from verified prior chains) writes a brief.{" "}
            <span className="text-neon_magenta">ARTIST</span> (creative, novel) designs the product.{" "}
            <span className="text-neon_yellow">PRODUCT</span> is materialized, executed once, corrected if needed, and delivered as a .zip.
          </p>
          <button
            data-testid="evolve-btn"
            onClick={trigger}
            disabled={busy || !target.trim()}
            className="relative flex flex-col items-center justify-center gap-2 border-2 border-phosphor bg-phosphor/5 text-phosphor px-8 py-5 uppercase tracking-widest transition-colors hover:bg-phosphor hover:text-black disabled:opacity-40 disabled:cursor-not-allowed neon-text min-w-[220px]"
          >
            <Zap size={24} className={busy ? "animate-pulse" : ""} />
            <span className="font-bbs text-xl">{busy ? "BUILDING…" : "BUILD"}</span>
            <span className="label-xs text-phosphor2">
              {busy ? currentStage || "calling AI…" : "▶ run the chain"}
            </span>
          </button>
        </div>
      </div>
    </section>
  );
};
