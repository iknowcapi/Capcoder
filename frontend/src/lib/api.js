import axios from "axios";
import { getJwt } from "@/lib/authClient";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// Anonymous session id — created once per browser, persisted in localStorage.
// Sent on every /api/* request as `X-Capcode-Session` so the backend can
// scope reads/writes to this browser's chains.
function _getAnonSessionId() {
  const KEY = "capcode.session_id";
  if (typeof window === "undefined") return "";
  let s = window.localStorage.getItem(KEY);
  if (!s) {
    s = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    window.localStorage.setItem(KEY, s);
  }
  return s;
}

// Attach the anon session header + Neon Auth JWT bearer + credentials to
// every /api/* request globally.
axios.interceptors.request.use(async (config) => {
  const url = config.url || "";
  if (url.startsWith(API) || url.includes("/api/")) {
    config.headers = config.headers || {};
    config.headers["X-Capcode-Session"] = _getAnonSessionId();
    // Neon Better Auth JWT (only present when the user is signed in).
    try {
      const jwt = await getJwt();
      if (jwt) config.headers["Authorization"] = `Bearer ${jwt}`;
    } catch (_) { /* noop */ }
    config.withCredentials = true;
  }
  return config;
});

export const api = {
  status: () => axios.get(`${API}/status`).then((r) => r.data),
  evolve: (target_prompt, session_id = undefined) =>
    axios
      .post(`${API}/evolve`, { target_prompt, depth: 1, session_id }, { timeout: 30000 })
      .then((r) => r.data),
  listChains: () => axios.get(`${API}/chains`).then((r) => r.data),
  getChain: (id) => axios.get(`${API}/chains/${id}`).then((r) => r.data),
  verifyChain: (id) => axios.post(`${API}/chains/${id}/verify`).then((r) => r.data),
  pushChain: (id, session_id, repo, isPrivate = true) =>
    axios.post(`${API}/chains/${id}/push`, { session_id, repo, private: isPrivate }).then((r) => r.data),
  // ---- Neon Managed Better Auth ----
  authMe: () => axios.get(`${API}/auth/me`).then((r) => r.data),
  authLogout: () => axios.post(`${API}/auth/logout`).then((r) => r.data),
  authConfig: () => axios.get(`${API}/auth/config`).then((r) => r.data),
};
