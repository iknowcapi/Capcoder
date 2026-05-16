import React, { useCallback, useEffect, useState } from "react";
import "@/App.css";
import { Toaster, toast } from "sonner";
import { api } from "@/lib/api";
import { TerminalHero } from "@/components/TerminalHero";
import { EvolveButton } from "@/components/EvolveButton";
import { ChainViewer } from "@/components/ChainViewer";

function App() {
  const [status, setStatus] = useState(null);
  const [chains, setChains] = useState([]);
  const [chain, setChain] = useState(null);
  const [busy, setBusy] = useState(false);
  const [depth, setDepth] = useState(3);
  const [stage, setStage] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.status(), api.listChains()]);
      setStatus(s);
      setChains(c);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleEvolve = async () => {
    setBusy(true);
    setStage("kicking off…");
    let pollId = null;
    try {
      const stub = await api.evolve(depth);
      setChain(stub);
      // poll until status === 'complete' or 'failed'
      await new Promise((resolve, reject) => {
        pollId = setInterval(async () => {
          try {
            const c = await api.getChain(stub.id);
            setChain(c);
            const done = (c.generations?.length || 0);
            setStage(`gen ${done}/${c.depth} ready…`);
            if (c.status === "complete") {
              clearInterval(pollId);
              resolve();
            } else if (c.status === "failed") {
              clearInterval(pollId);
              reject(new Error("evolution failed"));
            }
          } catch (e) {
            clearInterval(pollId);
            reject(e);
          }
        }, 3000);
      });
      toast.success(`CHAIN FORGED :: ${depth} GENS`);
      refresh();
    } catch (e) {
      console.error(e);
      const msg = e?.response?.data?.detail || e?.message || "evolution failed";
      toast.error(msg);
    } finally {
      if (pollId) clearInterval(pollId);
      setBusy(false);
      setStage(null);
    }
  };

  const openChain = async (id) => {
    try {
      const c = await api.getChain(id);
      setChain(c);
    } catch (e) {
      console.error(e);
    }
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

        <EvolveButton
          onEvolve={handleEvolve}
          busy={busy}
          depth={depth}
          setDepth={setDepth}
          currentStage={stage}
        />

        <ChainViewer chain={chain} />

        {chains.length > 0 && (
          <section
            className="panel p-4"
            data-testid="chain-history"
            style={{ borderColor: "rgba(255,234,0,0.35)" }}
          >
            <div className="label-xs text-neon_yellow mb-3">
              === [ ARCHIVE :: PRIOR CHAINS ] ===
            </div>
            <ul className="divide-y divide-phosphor/10 max-h-72 overflow-y-auto">
              {chains.map((c) => (
                <li key={c.id}>
                  <button
                    data-testid={`history-chain-${c.id.slice(0, 8)}`}
                    onClick={() => openChain(c.id)}
                    className={`w-full text-left py-2 px-1 font-mono text-xs hover:bg-phosphor/5 transition-colors ${
                      chain?.id === c.id ? "bg-phosphor/10" : ""
                    }`}
                  >
                    <div className="flex justify-between items-center gap-2">
                      <span className="text-phosphor truncate">
                        chain://{c.id.slice(0, 12)} — {c.generations?.length || 0} gens
                      </span>
                      <span className="text-phosphor3">
                        {c.generations
                          ?.map((g) => g.name || "?")
                          .join(" → ")
                          .slice(0, 60)}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer
          className="text-center text-phosphor3 font-mono text-[10px] sm:text-xs py-6 border-t border-phosphor/20"
          data-testid="footer"
        >
          ▒▓█ RECURSIVE.BBS // node-self-improving // {status?.nim_enabled ? "NIM-LIVE" : "NIM-OFFLINE"} // © {new Date().getFullYear()} █▓▒
        </footer>
      </main>
    </div>
  );
}

export default App;
