import React, { useState } from "react";
import { Download, FileCode, Folder, GitBranch, ExternalLink } from "lucide-react";
import { API } from "@/lib/api";
import axios from "axios";

const Bar = ({ label, value, max = 4, color = "phosphor" }) => {
  const pct = Math.max(0, Math.min(1, value / max));
  const filled = Math.round(pct * 18);
  const empty = 18 - filled;
  const cls =
    color === "magenta"
      ? "text-neon_magenta neon-magenta"
      : color === "cyan"
      ? "text-neon_cyan neon-cyan"
      : color === "yellow"
      ? "text-neon_yellow"
      : "text-phosphor neon-text";
  return (
    <div className="flex items-center justify-between gap-2 py-0.5 font-mono text-[11px] border-b border-phosphor/10">
      <span className="label-xs text-phosphor2 w-24">{label}</span>
      <span className={`${cls} flex-1`}>[{"|".repeat(filled)}{".".repeat(empty)}]</span>
      <span className={`${cls} tabular-nums w-10 text-right`}>{Number(value).toFixed(2)}</span>
    </div>
  );
};

const GenerationCard = ({ gen, chainId }) => {
  const [openFile, setOpenFile] = useState(gen.files?.[0]?.path || null);
  const files = gen.files || [];
  const selected = files.find((f) => f.path === openFile) || files[0];
  const r = gen.reward || {};
  const downloadHref = `${API}/chains/${chainId}/download/${gen.gen}`;

  return (
    <article
      className="panel p-4 sm:p-5 space-y-4"
      data-testid={`gen-card-${gen.gen}`}
      style={{ borderColor: "rgba(0,255,255,0.4)" }}
    >
      <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-phosphor/30 pb-3">
        <div>
          <div className="label-xs text-neon_cyan neon-cyan">
            [ GEN-{String(gen.gen).padStart(2, "0")} ]
          </div>
          <h3 className="font-bbs text-2xl sm:text-3xl text-phosphor neon-text uppercase tracking-widest leading-none mt-1">
            {gen.name || `gen-${gen.gen}`}
          </h3>
          <p className="text-xs text-phosphor2 mt-1 italic">{gen.tagline}</p>
        </div>
        <a
          data-testid={`download-gen-${gen.gen}`}
          href={downloadHref}
          className="flex items-center gap-2 border border-phosphor bg-phosphor/10 text-phosphor px-3 py-2 hover:bg-phosphor hover:text-black transition-colors label-xs neon-text whitespace-nowrap"
        >
          <Download size={14} /> .ZIP
        </a>
        <button
          data-testid={`vscode-gen-${gen.gen}`}
          onClick={async () => {
            try {
              const r = await axios.post(`${API}/chains/${chainId}/workspace/${gen.gen}`);
              const q = r.data.folder_query;
              // try common code-server URL patterns
              const host = window.location.host;
              const candidates = [
                `https://${host.replace(/^([^.]+)\./, "$1-code.")}/${q}`,
                `${window.location.protocol}//${host}:1111/${q}`,
                `${window.location.protocol}//${host}/vscode/${q}`,
              ];
              window.open(candidates[0], "_blank", "noopener");
              // eslint-disable-next-line no-alert
              window.setTimeout(() => alert(
                `Workspace ready at:\n${r.data.workspace_path}\n\nOpen Emergent's VSCode ` +
                `and use File > Open Folder to load it, or paste one of these URLs:\n\n` +
                candidates.join("\n")
              ), 300);
            } catch (e) {
              console.error(e);
            }
          }}
          className="flex items-center gap-2 border border-neon_cyan/60 text-neon_cyan px-3 py-2 hover:bg-neon_cyan hover:text-black transition-colors label-xs whitespace-nowrap"
        >
          <ExternalLink size={14} /> VSCODE
        </button>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-mono">
        <div className="bg-black border-l-2 border-neon_magenta p-2">
          <div className="label-xs text-neon_magenta neon-magenta mb-1">MUTATION</div>
          <div className="text-phosphor">{gen.improvement_note || "—"}</div>
        </div>
        <div className="bg-black border-l-2 border-neon_yellow p-2">
          <div className="label-xs text-neon_yellow mb-1">PALETTE</div>
          <div className="flex items-center gap-2 text-phosphor">
            <span
              className="inline-block w-4 h-4 border border-phosphor/30"
              style={{ background: gen.accent_hex || "#7cffb2" }}
            />
            <span>{gen.accent_hex || "—"}</span>
            <span
              className="inline-block w-4 h-4 border border-phosphor/30 ml-2"
              style={{ background: gen.accent2_hex || "#ff79c6" }}
            />
            <span>{gen.accent2_hex || "—"}</span>
          </div>
        </div>
      </div>

      <div className="bg-black border-l-2 border-phosphor/60 p-2 text-[11px] sm:text-xs font-mono text-phosphor2 leading-relaxed">
        <span className="label-xs text-phosphor3 mr-1">PHILOSOPHY ::</span>
        {gen.philosophy}
      </div>

      {/* files */}
      {files.length > 0 && (
        <div>
          <div className="label-xs text-neon_yellow mb-2">
            [ CODE :: {files.length} files ]
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr] gap-2">
            <div className="bg-black border border-phosphor/30 p-1.5 font-mono text-[10px] max-h-56 overflow-y-auto">
              {files.map((f) => (
                <button
                  key={f.path}
                  data-testid={`gen-${gen.gen}-file-${f.path}`}
                  onClick={() => setOpenFile(f.path)}
                  className={`flex items-center gap-1 w-full text-left px-2 py-1 hover:bg-phosphor/10 ${
                    openFile === f.path
                      ? "bg-phosphor/15 text-phosphor neon-text"
                      : "text-phosphor2"
                  }`}
                >
                  <FileCode size={9} />
                  <span className="truncate">{f.path}</span>
                </button>
              ))}
            </div>
            <pre className="ascii bg-black border border-phosphor/30 p-2 text-[10px] sm:text-[11px] font-mono overflow-auto max-h-56 text-phosphor leading-relaxed">
              {selected ? (
                <>
                  <div className="label-xs text-neon_cyan neon-cyan mb-1 sticky top-0 bg-black border-b border-phosphor/15 pb-1">
                    {selected.path}
                  </div>
                  <code>{selected.content}</code>
                </>
              ) : (
                "—"
              )}
            </pre>
          </div>
        </div>
      )}

      {/* critic + scores */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="bg-black border-l-2 border-neon_magenta p-2">
          <div className="label-xs text-neon_magenta neon-magenta mb-1">CRITIC</div>
          <p className="text-[11px] font-mono text-phosphor2 leading-relaxed">
            {gen.critic_notes}
          </p>
        </div>
        <div>
          <Bar label="HELP" value={r.helpfulness || 0} color="phosphor" />
          <Bar label="CORRECT" value={r.correctness || 0} color="cyan" />
          <Bar label="COHERE" value={r.coherence || 0} color="phosphor" />
          <Bar label="COMPLEX" value={r.complexity || 0} max={3} color="magenta" />
          <Bar label="VERBOSE" value={r.verbosity || 0} max={3} color="yellow" />
          <div className="flex justify-between mt-1 pt-1 border-t border-phosphor/30 font-mono">
            <span className="label-xs text-phosphor2">COMPOSITE</span>
            <span className="text-phosphor neon-text tabular-nums text-sm">
              {Number(gen.composite_score || 0).toFixed(3)}
            </span>
          </div>
        </div>
      </div>
    </article>
  );
};

export const ChainViewer = ({ chain, onVerify }) => {
  if (!chain) {
    return (
      <section
        className="panel p-8 text-center"
        data-testid="chain-empty"
      >
        <div className="font-bbs text-3xl text-phosphor neon-text mb-3 uppercase tracking-widest">
          ░░ no build yet ░░
        </div>
        <p className="text-phosphor3 font-mono text-sm">
          type a target prompt above and press BUILD to run the Teacher → Artist → Product chain.
        </p>
      </section>
    );
  }

  const downloadAll = `${API}/chains/${chain.id}/download`;
  const isComplete = chain.status === "complete";

  return (
    <section className="space-y-4 sm:space-y-6" data-testid="chain-viewer">
      <header
        className="panel p-4 sm:p-5 flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3"
        style={{ borderColor: "rgba(255,0,255,0.5)" }}
      >
        <div className="min-w-0 flex-1">
          <div className="label-xs text-neon_magenta neon-magenta">
            [ CHAIN :: {chain.id.slice(0, 12)} ]
          </div>
          <div className="font-bbs text-2xl sm:text-3xl text-phosphor neon-text uppercase tracking-widest leading-none mt-1">
            {chain.verified ? "✓ verified build" : "product build"}
          </div>
          {chain.target_prompt && (
            <p className="text-xs sm:text-sm text-phosphor2 mt-2 font-mono">
              <span className="text-phosphor3">target ::</span>{" "}
              <span data-testid="chain-target">{chain.target_prompt}</span>
            </p>
          )}
          <p className="text-xs text-phosphor3 mt-1 font-mono">
            {new Date(chain.created_at).toLocaleString()}
            {chain.fallback_used && (
              <span className="text-amber_warn ml-2">[correction pass used]</span>
            )}
          </p>
        </div>
        <div className="flex flex-col gap-2 shrink-0">
          {isComplete && (
            <a
              data-testid="download-chain"
              href={downloadAll}
              className="flex items-center gap-2 border-2 border-phosphor bg-phosphor/10 text-phosphor px-4 py-2 hover:bg-phosphor hover:text-black transition-colors uppercase tracking-widest neon-text"
            >
              <Download size={16} />
              <span className="font-bbs text-base">download .zip</span>
            </a>
          )}
          {isComplete && !chain.verified && (
            <button
              data-testid="verify-chain"
              onClick={() => onVerify?.(chain.id)}
              className="flex items-center gap-2 border-2 border-neon_yellow bg-neon_yellow/10 text-neon_yellow px-4 py-2 hover:bg-neon_yellow hover:text-black transition-colors uppercase tracking-widest"
            >
              <span className="font-bbs text-base">✓ works — verify</span>
            </button>
          )}
          {isComplete && chain.verified && (
            <span className="border-2 border-neon_yellow text-neon_yellow px-3 py-2 label-xs text-center">
              ✓ verified
            </span>
          )}
        </div>
      </header>

      {/* lineage breadcrumb */}
      <div
        className="panel p-3 flex items-center gap-2 overflow-x-auto"
        data-testid="chain-breadcrumb"
        style={{ borderColor: "rgba(57,255,20,0.25)" }}
      >
        <span className="label-xs text-phosphor3 shrink-0">HUMAN</span>
        <GitBranch size={12} className="text-neon_cyan shrink-0" />
        <span className="label-xs text-neon_cyan neon-cyan shrink-0 border border-neon_cyan/40 px-2 py-0.5">
          TEACHER
        </span>
        <GitBranch size={12} className="text-neon_magenta shrink-0" />
        <span className="label-xs text-neon_magenta neon-magenta shrink-0 border border-neon_magenta/40 px-2 py-0.5">
          ARTIST
        </span>
        <GitBranch size={12} className="text-neon_yellow shrink-0" />
        {chain.generations?.map((g) => (
          <span
            key={g.gen}
            className="label-xs text-neon_yellow shrink-0 border border-neon_yellow/40 px-2 py-0.5"
            data-testid={`breadcrumb-gen-${g.gen}`}
          >
            PRODUCT :: {g.name || "?"}
          </span>
        ))}
      </div>

      {chain.generations?.map((g) => (
        <GenerationCard key={g.gen} gen={g} chainId={chain.id} />
      ))}
    </section>
  );
};
