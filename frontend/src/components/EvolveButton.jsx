import React from "react";
import { Zap } from "lucide-react";

export const EvolveButton = ({ onEvolve, busy, depth, setDepth, currentStage }) => {
  return (
    <section
      className="panel p-6 sm:p-8 relative"
      data-testid="evolve-panel"
      style={{ borderColor: "rgba(57,255,20,0.5)" }}
    >
      <div className="flex items-center gap-2 text-neon_cyan neon-cyan label-xs mb-6">
        <span>=== [ AUTONOMOUS EVOLUTION ] ===</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-6 items-center">
        <div className="space-y-3 font-mono">
          <p className="text-phosphor neon-text text-base sm:text-lg">
            no input. no prompt. zero human in the loop.
          </p>
          <p className="text-phosphor2 text-xs sm:text-sm leading-relaxed">
            push the button. <span className="text-neon_cyan">glm-5.1</span> designs gen-2,
            a brand-new <span className="text-neon_yellow">code-builder application</span>{" "}
            (a FastAPI app that itself calls an LLM to write code).{" "}
            <span className="text-neon_magenta">minimax-m2.7</span> reviews it.{" "}
            <span className="text-neon_cyan">nemotron-super-49b</span> scores it. then gen-2's
            description is auto-fed back in to design gen-3. then gen-4. you download the
            entire lineage in one zip.
          </p>
          <div className="flex items-center gap-3 pt-2">
            <span className="label-xs text-phosphor3">depth:</span>
            {[2, 3, 4, 5].map((d) => (
              <button
                key={d}
                data-testid={`depth-${d}`}
                disabled={busy}
                onClick={() => setDepth(d)}
                className={`border px-3 py-1 text-xs font-mono transition-colors ${
                  depth === d
                    ? "border-phosphor bg-phosphor/15 text-phosphor neon-text"
                    : "border-phosphor/40 text-phosphor2 hover:border-phosphor"
                } disabled:opacity-30`}
              >
                {d}
              </button>
            ))}
            <span className="text-phosphor3 text-[10px] label-xs">
              (~{depth * 30}s)
            </span>
          </div>
        </div>

        <button
          data-testid="evolve-btn"
          onClick={onEvolve}
          disabled={busy}
          className="relative flex flex-col items-center justify-center gap-2 border-2 border-phosphor bg-phosphor/5 text-phosphor px-8 py-6 uppercase tracking-widest transition-colors hover:bg-phosphor hover:text-black disabled:opacity-40 disabled:cursor-not-allowed neon-text min-w-[220px]"
        >
          <Zap size={28} className={busy ? "animate-pulse" : ""} />
          <span className="font-bbs text-2xl">
            {busy ? "EVOLVING…" : "EVOLVE"}
          </span>
          <span className="label-xs text-phosphor2">
            {busy ? currentStage || "calling NIM…" : "▶ new chain"}
          </span>
        </button>
      </div>
    </section>
  );
};
