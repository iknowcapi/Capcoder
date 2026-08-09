import React, { useCallback, useEffect, useRef, useState } from "react";
import "@/App.css";
import { Toaster, toast } from "sonner";
import { LogIn, LogOut, Settings } from "lucide-react";
import { api, API } from "@/lib/api";
import { signInWithGoogle, signOut as neonSignOut } from "@/lib/authClient";
import { TerminalHero } from "@/components/TerminalHero";
import { EvolveButton } from "@/components/EvolveButton";
import { ChainViewer } from "@/components/ChainViewer";
import { SettingsPanel } from "@/components/SettingsPanel";

function getSessionId() {
  const KEY = "capcode.session_id";
  let s = localStorage.getItem(KEY);
  if (!s) {
    s = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(KEY, s);
  }
  return s;
}

function App() {
  const [sessionId] = useState(getSessionId);
  const [status, setStatus] = useState(null);
  const [chains, setChains] = useState([]);
  const [chain, setChain] = useState(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [assignments, setAssignments] = useState(null);
  const [historyFilter, setHistoryFilter] = useState("all"); // "all" | "verified"
  const [streamBuf, setStreamBuf] = useState({ teacher: "", artist: "" });
  const esRef = useRef(null);
  const [user, setUser] = useState(null);          // logged-in AuthUser or null
  const [checkingAuth, setCheckingAuth] = useState(true);

  // Watch Neon Better Auth session state — fires on sign-in/out & OAuth
  // redirect back from Google.
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const me = await api.authMe();
        if (alive) setUser(me);
      } catch (_) {
        if (alive) setUser(null);
      } finally {
        if (alive) setCheckingAuth(false);
      }
    };
    load();
    // Re-check auth every 60s to keep the JWT fresh (Neon JWTs expire in 15m
    // but authClient.token() auto-refreshes from the session cookie).
    const iv = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(iv); };
  }, []);

  const handleSignIn = async () => {
    try { await signInWithGoogle(); }
    catch (e) { toast.error(e?.message || "sign-in failed"); }
  };

  const handleSignOut = async () => {
    try { await neonSignOut(); } catch (_) { /* noop */ }
    try { await api.authLogout(); } catch (_) { /* noop */ }
    setUser(null);
    toast.success("SIGNED OUT");
  };

  const refresh = useCallback(async () => {
    try {
      const [s, c] = await Promise.all([api.status(), api.listChains()]);
      setStatus(s);
      setChains(c);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const handleEvolve = async (targetPrompt) => {
    setBusy(true);
    setStage("kicking off…");
    setStreamBuf({ teacher: "", artist: "" });
    let pollId = null;
    try {
      const stub = await api.evolve(targetPrompt, sessionId);
      setChain(stub);
      // Open SSE stream so we can render Teacher/Artist tokens live.
      try { esRef.current && esRef.current.close(); } catch { /* noop */ }
      const anonSid = (typeof window !== "undefined" && localStorage.getItem("capcode.session_id")) || "";
      const streamUrl = `${API}/chains/${stub.id}/stream?session_id=${encodeURIComponent(anonSid)}`;
      const es = new EventSource(streamUrl, { withCredentials: true });
      esRef.current = es;
      es.addEventListener("teacher_delta", (ev) => {
        setStreamBuf((b) => ({ ...b, teacher: b.teacher + ev.data + (ev.data.endsWith(" ") ? "" : "") }));
      });
      es.addEventListener("artist_delta", (ev) => {
        setStreamBuf((b) => ({ ...b, artist: b.artist + ev.data }));
      });
      es.addEventListener("stage", (ev) => setStage(String(ev.data || "").trim()));
      es.addEventListener("done", () => { try { es.close(); } catch { /* noop */ } });
      es.onerror = () => { try { es.close(); } catch { /* noop */ } };

      await new Promise((resolve, reject) => {
        pollId = setInterval(async () => {
          try {
            const c = await api.getChain(stub.id);
            setChain(c);
            if (c.status === "complete") { clearInterval(pollId); resolve(); }
            else if (c.status === "failed") {
              clearInterval(pollId);
              reject(new Error(c.error || "build failed"));
            }
          } catch (e) { clearInterval(pollId); reject(e); }
        }, 3000);
      });
      toast.success("PRODUCT BUILT");
      refresh();
    } catch (e) {
      console.error(e);
      const msg = e?.response?.data?.detail || e?.message || "build failed";
      toast.error(msg);
    } finally {
      if (pollId) clearInterval(pollId);
      try { esRef.current && esRef.current.close(); } catch { /* noop */ }
      esRef.current = null;
      setBusy(false);
      setStage(null);
    }
  };

  const openChain = async (id) => {
    try { const c = await api.getChain(id); setChain(c); } catch (e) { console.error(e); }
  };

  const handleVerify = async (id) => {
    try {
      await api.verifyChain(id);
      toast.success("VERIFIED :: ADDED TO TEACHER EXEMPLARS");
      const c = await api.getChain(id);
      setChain(c);
      refresh();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "verify failed");
    }
  };

  const handlePush = async (id, repo, isPrivate) => {
    try {
      const r = await api.pushChain(id, sessionId, repo, isPrivate);
      toast.success(`PUSHED :: ${r.repo}`);
      window.open(r.url, "_blank", "noopener");
      return r;
    } catch (e) {
      toast.error(e?.response?.data?.detail || "push failed");
      throw e;
    }
  };

  return (
    <div className="App relative crt-scanlines crt-vignette grain" data-testid="app-root">
      <div className="scan-drift" aria-hidden />
      <Toaster position="bottom-right" toastOptions={{
        style: {
          background: "#080c08", border: "1px solid rgba(57,255,20,0.5)",
          color: "#39FF14", borderRadius: 0,
          fontFamily: "'IBM Plex Mono', monospace",
          fontSize: "12px", textTransform: "uppercase", letterSpacing: "0.08em",
        },
      }} />

      <main className="relative z-10 max-w-7xl mx-auto p-3 sm:p-6 lg:p-8 space-y-4 sm:space-y-6">
        <TerminalHero status={status} />

        <div className="flex items-center justify-end gap-2">
          {user ? (
            <div className="flex items-center gap-2" data-testid="auth-user">
              {user.picture && (
                <img src={user.picture} alt={user.name}
                     className="w-6 h-6 rounded-full border border-phosphor/40" />
              )}
              <span className="text-xs font-mono text-phosphor2 hidden sm:inline">
                {user.name || user.email}
              </span>
              <button
                data-testid="sign-out"
                onClick={handleSignOut}
                className="flex items-center gap-2 border border-phosphor/40 text-phosphor2 px-3 py-2 hover:bg-phosphor/10 transition-colors label-xs"
              >
                <LogOut size={14} /> sign out
              </button>
            </div>
          ) : (
            !checkingAuth && (
              <button
                data-testid="sign-in"
                onClick={handleSignIn}
                className="flex items-center gap-2 border border-neon_cyan/60 text-neon_cyan px-3 py-2 hover:bg-neon_cyan hover:text-black transition-colors label-xs neon-cyan"
              >
                <LogIn size={14} /> sign in with google
              </button>
            )
          )}
          <button
            data-testid="open-settings"
            onClick={() => setSettingsOpen(true)}
            className="flex items-center gap-2 border border-neon_cyan/60 text-neon_cyan px-3 py-2 hover:bg-neon_cyan hover:text-black transition-colors label-xs neon-cyan"
          >
            <Settings size={14} /> model settings
          </button>
        </div>

        <EvolveButton
          onEvolve={handleEvolve} busy={busy}
          currentStage={stage} assignments={assignments}
        />

        <ChainViewer
          chain={chain}
          onVerify={handleVerify}
          onPush={handlePush}
          streamBuf={streamBuf}
        />

        {chains.length > 0 && (
          <section className="panel p-4" data-testid="chain-history"
                   style={{ borderColor: "rgba(255,234,0,0.35)" }}>
            <div className="flex items-center justify-between mb-3">
              <div className="label-xs text-neon_yellow">=== [ ARCHIVE :: PRIOR CHAINS ] ===</div>
              <div className="flex gap-1 text-[11px] font-mono">
                <button
                  data-testid="filter-all"
                  onClick={() => setHistoryFilter("all")}
                  className={`px-2 py-1 border ${historyFilter === "all"
                    ? "border-phosphor bg-phosphor/15 text-phosphor neon-text"
                    : "border-phosphor/40 text-phosphor2 hover:border-phosphor"}`}
                >all</button>
                <button
                  data-testid="filter-verified"
                  onClick={() => setHistoryFilter("verified")}
                  className={`px-2 py-1 border ${historyFilter === "verified"
                    ? "border-neon_yellow bg-neon_yellow/15 text-neon_yellow"
                    : "border-phosphor/40 text-phosphor2 hover:border-neon_yellow"}`}
                >✓ verified</button>
              </div>
            </div>
            <ul className="divide-y divide-phosphor/10 max-h-72 overflow-y-auto">
              {chains
                .filter((c) => historyFilter === "all" || c.verified)
                .map((c) => (
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
                        {c.verified && <span className="text-neon_yellow">✓ </span>}
                        chain://{c.id.slice(0, 12)}
                        {c.target_prompt && <span className="text-phosphor2"> — {c.target_prompt.slice(0, 50)}</span>}
                      </span>
                      <span className="text-phosphor3 shrink-0">
                        {c.status === "failed" ? "▲ failed" : `${c.generations?.length || 0} gen`}
                      </span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer className="text-center text-phosphor3 font-mono text-[10px] sm:text-xs py-6 border-t border-phosphor/20" data-testid="footer">
          ▒▓█ CAPCODE // node-self-improving // session {sessionId.slice(0, 8)} // © {new Date().getFullYear()} █▓▒
        </footer>
      </main>

      <SettingsPanel
        sessionId={sessionId}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onSaved={(a) => { setAssignments(a); toast.success("agents saved"); }}
      />
    </div>
  );
}

export default App;
