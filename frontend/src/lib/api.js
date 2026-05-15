import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

export const api = {
  status: () => axios.get(`${API}/status`).then((r) => r.data),
  createBuild: (prompt, parent_id = null) =>
    axios.post(`${API}/builds`, { prompt, parent_id }).then((r) => r.data),
  listBuilds: () => axios.get(`${API}/builds`).then((r) => r.data),
  getBuild: (id) => axios.get(`${API}/builds/${id}`).then((r) => r.data),
  feedback: (id, vote) =>
    axios.post(`${API}/builds/${id}/feedback`, { vote }).then((r) => r.data),
  leaderboard: () => axios.get(`${API}/leaderboard`).then((r) => r.data),
  lineage: () => axios.get(`${API}/lineage`).then((r) => r.data),
};
