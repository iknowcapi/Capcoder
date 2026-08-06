import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { API } from "@/lib/api";
import { Search, Save, RefreshCw, X, Zap, DollarSign } from "lucide-react";

const ROLES = [
  { key: "teacher", label: "TEACHER", desc: "rigid, strict; writes the Artist's brief from your target" },
  { key: "artist",  label: "ARTIST",  desc: "creative, novel; designs the actual product" },
  { key: "rater",   label: "RATER",   desc: "scores the finished product on 5 dimensions" },
];

const PriceBadge = ({ tier }) => {
  const map = {
    free: { text: "FREE", cls: "border-phosphor text-phosphor" },
    $: { text: "$", cls: "border-neon_cyan text-neon_cyan" },
    $$: { text: "$$", cls: "border-neon_yellow text-neon_yellow" },
    $$$: { text: "$$$", cls: "border-neon_magenta text-neon_magenta" },
  };
  const m = map[tier] || map["$"];
  return (
    <span className={`inline-block px-2 py-0.5 border font-mono text-[10px] label-xs ${m.cls}`}>
      {m.text}
    </span>
  );
};

export const SettingsPanel = ({ sessionId, open, onClose, onSaved }) => {
  const [catalog, setCatalog] = useState([]);
  const [defaults, setDefaults] = useState(null);
  const [settings, setSettings] = useState({});
  const [activeRole, setActiveRole] = useState("teacher");
  const [query, setQuery] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [uncensoredOnly, setUncensoredOnly] = useState(false);
  const [tierFilter, setTierFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [{ data: cat }, { data: s }] = await Promise.all([
        axios.get(`${API}/providers/models`),
        axios.get(`${API}/settings`, { params: { session_id: sessionId } }),
      ]);
      setCatalog(cat.models || []);
      setDefaults(cat.defaults || {});
      setSettings({
        teacher: s.teacher,
        artist: s.artist,
        rater: s.rater,
        keys: { openrouter: "", venice: "", nvidia: "" },
        keys_set: s.keys_set || {},
        github: { username: s.github?.username || "", token: "" },
        github_token_set: !!s.github?.token_set,
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && sessionId) loadAll();
  }, [open, sessionId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return catalog.filter((m) => {
      if (providerFilter !== "all" && m.provider !== providerFilter) return false;
      if (uncensoredOnly && !m.uncensored) return false;
      if (tierFilter !== "all" && m.price_tier !== tierFilter) return false;
      if (q && !`${m.id} ${m.display_name} ${m.description}`.toLowerCase().includes(q))
        return false;
      return true;
    });
  }, [catalog, query, providerFilter, uncensoredOnly, tierFilter]);

  const pick = (model) => {
    setSettings((s) => ({
      ...s,
      [activeRole]: { provider: model.provider, model: model.id },
    }));
  };

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        teacher: settings.teacher,
        artist: settings.artist,
        rater: settings.rater,
      };
      // Only send non-empty keys; empty string clears a saved key.
      const outKeys = {};
      ["openrouter", "venice", "nvidia"].forEach((p) => {
        const v = settings.keys?.[p];
        if (typeof v === "string" && v.length > 0) outKeys[p] = v;
      });
      if (Object.keys(outKeys).length) payload.keys = outKeys;
      const gh = settings.github || {};
      if (gh.username !== undefined || gh.token) {
        payload.github = {};
        if (gh.username !== undefined) payload.github.username = gh.username;
        if (gh.token) payload.github.token = gh.token;
      }
      await axios.post(`${API}/settings`, payload, {
        params: { session_id: sessionId },
      });
      onSaved?.(settings);
      onClose?.();
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/85 flex items-start justify-center p-2 sm:p-6"
      data-testid="settings-panel"
      onClick={(e) => e.target === e.currentTarget && onClose?.()}
    >
      <div
        className="panel w-full max-w-5xl max-h-[95vh] flex flex-col"
        style={{ borderColor: "rgba(0,255,255,0.5)" }}
      >
        {/* header */}
        <div className="flex items-center justify-between border-b border-phosphor/30 p-4">
          <div>
            <div className="label-xs text-neon_cyan neon-cyan">
              [ CAPCODE :: MODEL SETTINGS ]
            </div>
            <div className="font-bbs text-2xl text-phosphor neon-text uppercase tracking-widest mt-1">
              choose your agents
            </div>
            <div className="label-xs text-phosphor3 mt-1">
              saved per device — this browser only
            </div>
          </div>
          <button
            data-testid="settings-close"
            onClick={onClose}
            className="border border-phosphor/40 text-phosphor p-2 hover:bg-phosphor hover:text-black"
          >
            <X size={16} />
          </button>
        </div>

        {/* role tabs */}
        <div className="flex border-b border-phosphor/30 overflow-x-auto">
          {ROLES.map((r) => {
            const current = settings[r.key] || {};
            const isDefault =
              defaults?.[r.key]?.model === current.model &&
              defaults?.[r.key]?.provider === current.provider;
            return (
              <button
                key={r.key}
                data-testid={`role-tab-${r.key}`}
                onClick={() => setActiveRole(r.key)}
                className={`min-w-[170px] text-left px-3 py-3 border-r border-phosphor/20 last:border-r-0 transition-colors ${
                  activeRole === r.key
                    ? "bg-phosphor/10 text-phosphor neon-text"
                    : "text-phosphor2 hover:bg-phosphor/5"
                }`}
              >
                <div className="label-xs">
                  {r.label} {isDefault && <span className="text-phosphor3 ml-1">(default)</span>}
                </div>
                <div className="text-[10px] text-phosphor3 mt-1">{r.desc}</div>
                <div className="text-[11px] text-neon_magenta neon-magenta mt-1 font-mono truncate">
                  {current.model || "—"}
                </div>
              </button>
            );
          })}
        </div>

        {/* filters */}
        <div className="p-4 border-b border-phosphor/20 space-y-3">
          <div className="relative">
            <Search size={14} className="absolute left-2 top-2.5 text-phosphor3" />
            <input
              data-testid="settings-search"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="search by name, id, or description…"
              className="w-full bg-black border border-phosphor/40 text-phosphor pl-8 pr-3 py-2 font-mono text-xs"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-[11px] font-mono">
            <span className="label-xs text-phosphor3">provider:</span>
            {["all", "openrouter", "nvidia", "venice"].map((p) => (
              <button
                key={p}
                data-testid={`filter-provider-${p}`}
                onClick={() => setProviderFilter(p)}
                className={`border px-2 py-1 transition-colors ${
                  providerFilter === p
                    ? "border-phosphor bg-phosphor/15 text-phosphor"
                    : "border-phosphor/30 text-phosphor2 hover:border-phosphor"
                }`}
              >
                {p}
              </button>
            ))}
            <span className="label-xs text-phosphor3 ml-4">tier:</span>
            {["all", "free", "$", "$$", "$$$"].map((t) => (
              <button
                key={t}
                data-testid={`filter-tier-${t}`}
                onClick={() => setTierFilter(t)}
                className={`border px-2 py-1 transition-colors ${
                  tierFilter === t
                    ? "border-phosphor bg-phosphor/15 text-phosphor"
                    : "border-phosphor/30 text-phosphor2 hover:border-phosphor"
                }`}
              >
                {t}
              </button>
            ))}
            <label className="ml-4 flex items-center gap-1 cursor-pointer">
              <input
                data-testid="filter-uncensored"
                type="checkbox"
                checked={uncensoredOnly}
                onChange={(e) => setUncensoredOnly(e.target.checked)}
              />
              <span className="label-xs text-neon_magenta neon-magenta">UNCENSORED ONLY</span>
            </label>
            <span className="ml-auto label-xs text-phosphor3">
              {filtered.length} / {catalog.length}
            </span>
          </div>
        </div>

        {/* model list */}
        <div
          className="overflow-y-auto flex-1 p-2"
          data-testid="model-list"
        >
          {loading && (
            <div className="text-center py-8 text-phosphor3 font-mono text-sm">
              loading catalog…
            </div>
          )}
          {!loading && filtered.length === 0 && (
            <div className="text-center py-8 text-phosphor3 font-mono text-sm">
              no models match filters
            </div>
          )}
          <ul className="divide-y divide-phosphor/10">
            {filtered.map((m) => {
              const selected =
                settings[activeRole]?.model === m.id &&
                settings[activeRole]?.provider === m.provider;
              return (
                <li key={`${m.provider}:${m.id}`}>
                  <button
                    data-testid={`model-${m.provider}-${m.id}`}
                    onClick={() => pick(m)}
                    className={`w-full text-left py-2 px-3 flex items-center gap-3 hover:bg-phosphor/5 transition-colors ${
                      selected ? "bg-phosphor/10 border-l-2 border-phosphor" : ""
                    }`}
                  >
                    <PriceBadge tier={m.price_tier} />
                    <div className="flex-1 min-w-0">
                      <div className="text-phosphor font-mono text-xs truncate">
                        {m.id}
                      </div>
                      {m.description && (
                        <div className="text-phosphor3 text-[10px] truncate mt-0.5">
                          {m.description}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] label-xs shrink-0">
                      <span className="text-phosphor2">{m.provider}</span>
                      {m.uncensored && (
                        <span className="text-neon_magenta neon-magenta">UNCEN</span>
                      )}
                      {m.coding && (
                        <span className="text-neon_cyan neon-cyan">CODE</span>
                      )}
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {/* BYOK + GitHub */}
        <div className="border-t border-phosphor/30 p-4 space-y-3 max-h-72 overflow-y-auto"
             data-testid="keys-section">
          <div className="label-xs text-neon_cyan neon-cyan">
            [ YOUR KEYS :: BYOK ]
          </div>
          <p className="text-[10px] text-phosphor3 font-mono">
            Paste your own OpenRouter / Venice / NVIDIA keys. If set, CapCode uses YOUR keys
            for every LLM call — leave blank to keep using the server defaults.
            Keys are stored per-device and never sent back to your browser once saved.
          </p>
          {["openrouter", "venice", "nvidia"].map((p) => (
            <div key={p} className="flex items-center gap-2">
              <label className="w-28 text-xs font-mono text-phosphor2 uppercase">
                {p}
                {settings.keys_set?.[p] && (
                  <span className="ml-1 text-phosphor neon-text">✓</span>
                )}
              </label>
              <input
                data-testid={`key-input-${p}`}
                type="password"
                placeholder={settings.keys_set?.[p] ? "•••••••• (saved — retype to replace, empty to keep)" : "paste key"}
                value={settings.keys?.[p] || ""}
                onChange={(e) => setSettings((s) => ({
                  ...s,
                  keys: { ...(s.keys || {}), [p]: e.target.value },
                }))}
                className="flex-1 bg-black border border-phosphor/40 focus:border-neon_cyan text-phosphor px-2 py-1 font-mono text-xs outline-none"
              />
            </div>
          ))}

          <div className="pt-2 mt-2 border-t border-phosphor/20">
            <div className="label-xs text-neon_cyan neon-cyan mb-2">
              [ GITHUB :: PUSH TARGET ]
            </div>
            <p className="text-[10px] text-phosphor3 font-mono mb-2">
              To use &ldquo;push to github&rdquo;, save your username + a PAT (fine-grained, scope: repo).
            </p>
            <div className="flex items-center gap-2 mb-2">
              <label className="w-28 text-xs font-mono text-phosphor2 uppercase">username</label>
              <input
                data-testid="github-username"
                value={settings.github?.username || ""}
                onChange={(e) => setSettings((s) => ({
                  ...s, github: { ...(s.github || {}), username: e.target.value },
                }))}
                placeholder="octocat"
                className="flex-1 bg-black border border-phosphor/40 focus:border-neon_cyan text-phosphor px-2 py-1 font-mono text-xs outline-none"
              />
            </div>
            <div className="flex items-center gap-2">
              <label className="w-28 text-xs font-mono text-phosphor2 uppercase">
                token {settings.github_token_set && <span className="text-phosphor neon-text">✓</span>}
              </label>
              <input
                data-testid="github-token"
                type="password"
                placeholder={settings.github_token_set ? "•••••••• (saved)" : "ghp_..."}
                value={settings.github?.token || ""}
                onChange={(e) => setSettings((s) => ({
                  ...s, github: { ...(s.github || {}), token: e.target.value },
                }))}
                className="flex-1 bg-black border border-phosphor/40 focus:border-neon_cyan text-phosphor px-2 py-1 font-mono text-xs outline-none"
              />
            </div>
          </div>
        </div>

        {/* footer */}
        <div className="flex items-center justify-between border-t border-phosphor/30 p-4 gap-2">
          <div className="text-phosphor3 label-xs">
            {activeRole.toUpperCase()} :: {settings[activeRole]?.provider || "—"} /{" "}
            {settings[activeRole]?.model || "—"}
          </div>
          <div className="flex items-center gap-2">
            <button
              data-testid="settings-reset"
              onClick={() =>
                setSettings({
                  teacher: defaults?.teacher,
                  artist: defaults?.artist,
                  rater: defaults?.rater,
                })
              }
              className="border border-phosphor/40 text-phosphor2 px-3 py-2 text-xs label-xs hover:bg-phosphor hover:text-black"
            >
              <RefreshCw size={12} className="inline mr-1" /> reset
            </button>
            <button
              data-testid="settings-save"
              onClick={save}
              disabled={saving}
              className="flex items-center gap-2 border border-phosphor bg-phosphor/10 text-phosphor px-4 py-2 hover:bg-phosphor hover:text-black label-xs neon-text disabled:opacity-30"
            >
              <Save size={12} /> {saving ? "saving…" : "save & close"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
