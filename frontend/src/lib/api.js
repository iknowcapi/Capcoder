import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

// All auth requests must send/receive the httpOnly cookie.
const authAxios = axios.create({ withCredentials: true });

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
  // ---- Emergent-managed Google Auth ----
  authExchange: (session_id) =>
    authAxios.post(`${API}/auth/session`, { session_id }).then((r) => r.data),
  authMe: () => authAxios.get(`${API}/auth/me`).then((r) => r.data),
  authLogout: () => authAxios.post(`${API}/auth/logout`).then((r) => r.data),
};
