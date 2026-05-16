import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = {
  status: () => axios.get(`${API}/status`).then((r) => r.data),
  evolve: (depth = 3) =>
    axios.post(`${API}/evolve`, { depth }, { timeout: 30000 }).then((r) => r.data),
  listChains: () => axios.get(`${API}/chains`).then((r) => r.data),
  getChain: (id) => axios.get(`${API}/chains/${id}`).then((r) => r.data),
};
