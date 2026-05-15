import React from "react";
import { ThumbsUp, ThumbsDown, GitBranch, FileJson } from "lucide-react";

const Bar = ({ label, value, max = 4, color = "phosphor" }) => {
  const pct = Math.max(0, Math.min(1, value / max));
  const filled = Math.round(pct * 20);
  const empty = 20 - filled;
  const colorClass =
    color === "magenta"
      ? "text-neon_magenta neon-magenta"
      : color === "cyan"
      ? "text-neon_cyan neon-cyan"
      : color === "yellow"
      ? "text-neon_yellow"
      : "text-phosphor neon-text";
  return (
    <div className="flex items-center justify-between gap-3 py-1 font-mono text-xs sm:text-sm border-b border-phosphor/15">
      <span className="label-xs text-phosphor2 w-24">{label}</span>
      <span className={`${colorClass} flex-1 truncate`}>
        [{"|".repeat(filled)}{".".repeat(empty)}]
      </span>
      <span className={`${colorClass} tabular-nums w-12 text-right`}>{value.toFixed(2)}</span>
    </div>
  );
};

const JsonView = ({ obj }) => (
  <pre className="ascii bg-black border-l-2 border-neon_magenta p-3 sm:p-4 text-[11px] sm:text-xs font-mono overflow-x-auto max-h-72 overflow-y-auto">
    <code className="text-phosphor">
      {JSON.stringify(obj || {}, null, 2)
        .split("\n")
        .map((line, i) => {
          const m = line.match(/^(\s*)(".*?")(\s*:\s*)(.*)$/);
          if (m) {
            return (
              <div key={i}>
                {m[1]}
                <span className="text-neon_cyan">{m[2]}</span>
                <span className="text-phosphor3">{m[3]}</span>
                <span className="text-amber_warn">{m[4]}</span>
              </div>
            );
          }
          return <div key={i}>{line}</div>;
        })}
    </code>
  </pre>
);

export const BuildDetail = ({ build, onFeedback, onFork }) => {
  if (!build) {
    return (
      <section
        className="panel p-6 text-center text-phosphor3 font-mono"
        data-testid="build-detail-empty"
      >
        <div className="font-bbs text-2xl text-phosphor neon-text mb-2 uppercase">
          ░░ awaiting transmission ░░
        </div>
        <div className="text-sm">
          submit a prompt above to forge a new app-builder.
        </div>
      </section>
    );
  }

  const r = build.reward || {};
  return (
    <section className="panel p-4 sm:p-6 space-y-5" data-testid="build-detail">
      {/* header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-phosphor/30 pb-3">
        <div>
          <div className="label-xs text-neon_cyan neon-cyan">
            [ BUILD :: {build.id.slice(0, 12)} // GEN-{String(build.generation).padStart(3, "0")} ]
          </div>
          <div className="font-bbs text-3xl sm:text-4xl text-phosphor neon-text uppercase tracking-widest leading-none mt-1">
            {build.meta_builder_spec?.name || "untitled.builder"}
          </div>
          <div className="text-xs sm:text-sm text-phosphor2 mt-1">
            domain :: <span className="text-neon_magenta neon-magenta">{build.meta_builder_spec?.domain || "—"}</span>
            {" "}// dna :: <span className="text-amber_warn">{build.meta_builder_spec?.dna_signature || "—"}</span>
            {build.meta_builder_spec?.inherited_from && (
              <> // inherits :: <span className="text-neon_cyan">{String(build.meta_builder_spec.inherited_from).slice(0,8)}</span></>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            data-testid="feedback-up"
            onClick={() => onFeedback?.(build.id, 1)}
            className={`border px-3 py-2 transition-colors ${
              build.user_vote === 1
                ? "bg-phosphor text-black border-phosphor"
                : "border-phosphor/50 text-phosphor hover:bg-phosphor hover:text-black"
            }`}
            title="boost into future gene pool"
          >
            <ThumbsUp size={14} />
          </button>
          <button
            data-testid="feedback-down"
            onClick={() => onFeedback?.(build.id, -1)}
            className={`border px-3 py-2 transition-colors ${
              build.user_vote === -1
                ? "bg-destructive text-black border-destructive"
                : "border-destructive/50 text-destructive hover:bg-destructive hover:text-black"
            }`}
            title="suppress this lineage"
          >
            <ThumbsDown size={14} />
          </button>
          <button
            data-testid="fork-build"
            onClick={() => onFork?.(build.id)}
            className="flex items-center gap-1 border border-neon_cyan/60 text-neon_cyan px-3 py-2 hover:bg-neon_cyan hover:text-black transition-colors label-xs"
          >
            <GitBranch size={14} /> FORK
          </button>
        </div>
      </div>

      {/* prompt */}
      <div className="bg-black border border-phosphor/30 p-3 font-mono text-xs sm:text-sm">
        <span className="text-neon_magenta neon-magenta">user@bbs:~$ </span>
        <span className="text-phosphor">{build.user_prompt}</span>
      </div>

      {/* rater scorecard */}
      <div data-testid="rater-scorecard">
        <div className="label-xs text-neon_yellow mb-2">
          === [ NEMOTRON RATER // SCORECARD ] ===
        </div>
        <Bar label="HELPFULNESS" value={r.helpfulness || 0} color="phosphor" />
        <Bar label="CORRECTNESS" value={r.correctness || 0} color="cyan" />
        <Bar label="COHERENCE" value={r.coherence || 0} color="phosphor" />
        <Bar label="COMPLEXITY" value={r.complexity || 0} max={3} color="magenta" />
        <Bar label="VERBOSITY" value={r.verbosity || 0} max={3} color="yellow" />
        <div className="flex justify-between mt-3 pt-2 border-t border-phosphor/30 font-mono">
          <span className="label-xs text-phosphor2">COMPOSITE</span>
          <span
            data-testid="composite-score"
            className="text-phosphor neon-text text-lg tabular-nums"
          >
            {build.composite_score?.toFixed?.(3) ?? "0.000"}
          </span>
        </div>
      </div>

      {/* critic */}
      <div>
        <div className="label-xs text-neon_magenta neon-magenta mb-2">
          === [ MINIMAX CRITIC // NOTES ] ===
        </div>
        <div className="bg-black border-l-2 border-neon_magenta p-3 font-mono text-xs sm:text-sm text-phosphor2 leading-relaxed">
          {build.critic_notes}
        </div>
      </div>

      {/* artifacts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div>
          <div className="label-xs text-neon_cyan neon-cyan mb-2 flex items-center gap-2">
            <FileJson size={12} /> [ META.BUILDER.SPEC ]
          </div>
          <JsonView obj={build.meta_builder_spec} />
        </div>
        <div>
          <div className="label-xs text-amber_warn mb-2 flex items-center gap-2">
            <FileJson size={12} /> [ APP.SPEC ]
          </div>
          <JsonView obj={build.app_spec} />
        </div>
      </div>
    </section>
  );
};
