import React, { useCallback, useEffect, useState } from "react";
import "@/App.css";
import { Toaster, toast } from "sonner";
import { api } from "@/lib/api";
import { TerminalHero } from "@/components/TerminalHero";
import { PromptConsole } from "@/components/PromptConsole";
import { Pipeline } from "@/components/Pipeline";
import { BuildDetail } from "@/components/BuildDetail";
import { Leaderboard } from "@/components/Leaderboard";
import { LineageTimeline } from "@/components/LineageTimeline";

function App() {
  const [status, setStatus] = useState(null);
  const [builds, setBuilds] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [lineage, setLineage] = useState([]);
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [activeStage, setActiveStage] = useState(null);
  const [parentId, setParentId] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [s, b, lb, ln] = await Promise.all([
        api.status(),
        api.listBuilds(),
        api.leaderboard(),
        api.lineage(),
      ]);
      setStatus(s);
      setBuilds(b);
      setLeaderboard(lb);
      setLineage(ln.nodes || []);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleSubmit = async (prompt) => {
    setBusy(true);
    setActiveStage("gen");
    // staged UX cue (purely visual; real work happens in single request)
    const t1 = setTimeout(() => setActiveStage("crit"), 900);
    const t2 = setTimeout(() => setActiveStage("rate"), 1800);
    try {
      const build = await api.createBuild(prompt, parentId);
      setSelected(build);
      setParentId(null);
      toast.success(`BUILD FORGED :: ${build.id.slice(0, 8)} // GEN-${String(build.generation).padStart(3, "0")}`);
      await refresh();
    } catch (e) {
      console.error(e);
      toast.error("transmission failed");
    } finally {
      clearTimeout(t1);
      clearTimeout(t2);
      setBusy(false);
      setActiveStage(null);
    }
  };

  const handleSelect = async (id) => {
    try {
      const b = await api.getBuild(id);
      setSelected(b);
    } catch (e) {
      console.error(e);
    }
  };

  const handleFeedback = async (id, vote) => {
    try {
      const b = await api.feedback(id, vote);
      setSelected(b);
      toast.success(vote > 0 ? "→ boosted into gene pool" : "→ suppressed");
      refresh();
    } catch (e) {
      console.error(e);
    }
  };

  const handleFork = (id) => {
    setParentId(id);
    toast(`forking from ${id.slice(0, 8)} — type a mutation prompt`);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  return (
    <div className="App relative crt-scanlines crt-vignette grain" data-testid="app-root">
      <div className="scan-drift" aria-hidden />
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#080c08",
            border: "1px solid rgba(57,255,20,0.5)",
            color: "#39FF14",
            borderRadius: 0,
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: "12px",
            textTransform: "uppercase",
            letterSpacing: "0.08em",
          },
        }}
      />

      <main className="relative z-10 max-w-7xl mx-auto p-3 sm:p-6 lg:p-8 space-y-4 sm:space-y-6">
        <TerminalHero status={status} />
        <PromptConsole
          onSubmit={handleSubmit}
          busy={busy}
          parentId={parentId}
          onClearParent={() => setParentId(null)}
        />
        <Pipeline activeStage={activeStage} busy={busy} />

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 sm:gap-6">
          <BuildDetail build={selected} onFeedback={handleFeedback} onFork={handleFork} />
          <div className="space-y-4 sm:space-y-6">
            <Leaderboard
              items={leaderboard}
              selectedId={selected?.id}
              onSelect={handleSelect}
            />
            <RecentBuilds
              items={builds}
              selectedId={selected?.id}
              onSelect={handleSelect}
            />
          </div>
        </div>

        <LineageTimeline
          nodes={lineage}
          selectedId={selected?.id}
          onSelect={handleSelect}
        />

        <footer
          className="text-center text-phosphor3 font-mono text-[10px] sm:text-xs py-6 border-t border-phosphor/20"
          data-testid="footer"
        >
          ▒▓█ RECURSIVE.BBS // node-self-improving // © {new Date().getFullYear()} // press ⌘⏎ to execute █▓▒
        </footer>
      </main>
    </div>
  );
}

const RecentBuilds = ({ items, onSelect, selectedId }) => (
  <section
    className="panel p-4 sm:p-5"
    data-testid="recent-builds"
    style={{ borderColor: "rgba(255,234,0,0.35)" }}
  >
    <div className="label-xs text-neon_yellow mb-3">=== [ LIBRARY // ALL BUILDS ] ===</div>
    {(!items || items.length === 0) && (
      <div className="text-phosphor3 font-mono text-xs py-6 text-center">
        ░ no transmissions yet ░
      </div>
    )}
    <ul className="divide-y divide-phosphor/10 max-h-[400px] overflow-y-auto">
      {items?.map((b) => (
        <li key={b.id}>
          <button
            data-testid={`recent-build-${b.id.slice(0, 8)}`}
            onClick={() => onSelect(b.id)}
            className={`w-full text-left py-2 px-1 font-mono text-xs hover:bg-phosphor/5 transition-colors ${
              selectedId === b.id ? "bg-phosphor/10" : ""
            }`}
          >
            <div className="flex justify-between">
              <span className="text-phosphor truncate flex-1 pr-2">
                {b.app?.name || b.bot?.name || b.id.slice(0, 12)}
              </span>
              <span className="text-amber_warn tabular-nums">
                {Number(b.composite_score || 0).toFixed(2)}
              </span>
            </div>
            <div className="text-phosphor3 text-[10px] truncate mt-0.5">
              {b.user_prompt}
            </div>
          </button>
        </li>
      ))}
    </ul>
  </section>
);

export default App;
