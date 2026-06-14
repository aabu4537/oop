const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, init);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

// --- Types ---

export interface Team {
  team_id: string;
  name: string;
  fifa_code: string | null;
  elo_rating: number | null;
}

export interface Match {
  match_id: string;
  home_team_id: string | null;
  away_team_id: string | null;
  home_team_name: string | null;
  away_team_name: string | null;
  match_date: string;
  competition: string | null;
  season: string | null;
  home_score: number | null;
  away_score: number | null;
}

export interface Prediction {
  pred_id: string;
  match_id: string | null;
  model_version: string;
  home_win_prob: number;
  draw_prob: number;
  away_win_prob: number;
  brier_score: number | null;
  log_loss: number | null;
}

export interface PlayerMetric {
  metric_id: string;
  player_id: string | null;
  match_id: string | null;
  press_intensity: number | null;
  run_frequency: number | null;
  space_creation_idx: number | null;
  def_line_engagement: number | null;
}

export interface SimulateRequest {
  groups: Record<string, { name: string; elo: number }[]>;
  n_sims: number;
  seed?: number;
}

export interface SimulateResponse {
  results: Record<string, number | string>[];
  n_sims: number;
}

// --- Endpoints ---

export const getTeams = () => apiFetch<Team[]>("/teams").catch(() => [] as Team[]);

export const getMatches = (params?: { competition?: string; season?: string; limit?: number }) => {
  const qs = new URLSearchParams(
    Object.fromEntries(
      Object.entries(params ?? {})
        .filter(([, v]) => v != null && v !== "")
        .map(([k, v]) => [k, String(v)])
    )
  ).toString();
  return apiFetch<Match[]>(`/matches${qs ? `?${qs}` : ""}`).catch(() => [] as Match[]);
};

export const getPredictions = (modelVersion?: string) => {
  const qs = modelVersion ? `?model_version=${modelVersion}` : "";
  return apiFetch<Prediction[]>(`/predictions${qs}`).catch(() => [] as Prediction[]);
};

export const getPlayerMetrics = (playerId: string) =>
  apiFetch<PlayerMetric[]>(`/players/${playerId}/metrics`).catch(() => [] as PlayerMetric[]);

export const simulate = (req: SimulateRequest) =>
  apiFetch<SimulateResponse>("/simulate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

export const simulateWC2026 = (nSims = 10_000, seed = 42) =>
  apiFetch<SimulateResponse>(`/simulate/wc2026?n_sims=${nSims}&seed=${seed}`, { method: "POST" });
