import React, { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

/**
 * Emergent Google Auth callback.
 * REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH.
 *
 * Rendered synchronously when window.location.hash contains `session_id=` (see App.js).
 * Exchanges the session_id for a persistent httpOnly cookie, then hands the user
 * back to the main app.
 */
export const AuthCallback = ({ onDone }) => {
  const processed = useRef(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    // useRef guard, set synchronously — StrictMode-safe (this component only
    // runs once per full-page auth callback).
    if (processed.current) return;
    processed.current = true;

    const hash = window.location.hash || "";
    const m = hash.match(/session_id=([^&]+)/);
    const sid = m ? decodeURIComponent(m[1]) : null;
    if (!sid) {
      setErr("no session_id in URL fragment");
      return;
    }

    (async () => {
      try {
        const user = await api.authExchange(sid);
        // Wipe the fragment so a refresh doesn't retry the exchange.
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
        onDone?.(user);
      } catch (e) {
        console.error(e);
        setErr(e?.response?.data?.detail || "auth exchange failed");
      }
    })();
  }, [onDone]);

  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-6"
         data-testid="auth-callback">
      <div className="border border-phosphor/40 p-8 font-mono">
        <div className="label-xs text-neon_cyan neon-cyan mb-2">
          [ CAPCODE :: AUTH HANDSHAKE ]
        </div>
        <div className="font-bbs text-2xl text-phosphor neon-text uppercase tracking-widest mb-2">
          {err ? "▲ handshake failed" : "signing you in…"}
        </div>
        {err ? (
          <p className="text-red-400 text-xs" data-testid="auth-error">{err}</p>
        ) : (
          <p className="text-phosphor2 text-xs">exchanging session token — please wait</p>
        )}
      </div>
    </div>
  );
};
