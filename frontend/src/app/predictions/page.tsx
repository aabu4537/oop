"use client";

import { useEffect, useState, useMemo } from "react";
import { getPredictions, type Prediction } from "@/lib/api";
import { getFlag } from "@/lib/flags";

const MODEL_DISPLAY: Record<string, string> = {
  "xgb_v1.0": "XGBoost",
  "lr_v1.0": "Linear Regression",
};

const MODEL_DESCRIPTIONS: Record<string, string> = {
  "xgb_v1.0":
    "XGBoost is a gradient boosting model that builds an ensemble of decision trees to capture non-linear relationships between team metrics and match results. It generally outperforms Linear Regression on this dataset by learning complex interactions between Elo ratings, pressing intensity, and tournament context.",
  "lr_v1.0":
    "Linear Regression predicts match outcomes by finding a weighted combination of team strength (Elo rating) and out-of-possession metrics. It is fast, interpretable, and performs well when the relationship between features and outcomes is roughly linear. Best used as a baseline to compare against more complex models.",
};

type ModelKey = "" | "xgb_v1.0" | "lr_v1.0";

const MODEL_OPTIONS: { value: ModelKey; label: string }[] = [
  { value: "", label: "All models" },
  { value: "xgb_v1.0", label: "XGBoost" },
  { value: "lr_v1.0", label: "Linear Regression" },
];

const TODAY = new Date().toISOString().slice(0, 10);

function ProbBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-white/40 w-16 shrink-0 truncate">{label}</span>
      <div className="flex-1 bg-white/10 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value * 100}%` }} />
      </div>
      <span className="text-white/60 tabular-nums w-10 text-right">{(value * 100).toFixed(1)}%</span>
    </div>
  );
}

export default function PredictionsPage() {
  const [all, setAll] = useState<Prediction[]>([]);
  const [model, setModel] = useState<ModelKey>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    // Load a large batch; filter client-side to WC 2026 + upcoming
    getPredictions(undefined, 1000)
      .then(setAll)
      .finally(() => setLoading(false));
  }, []);

  const preds = useMemo(() => {
    return all.filter((p) => {
      const isWC = p.competition === "FIFA World Cup";
      const isUpcoming = p.match_date != null && p.match_date >= TODAY;
      const matchesModel = model === "" || p.model_version === model;
      return isWC && isUpcoming && matchesModel;
    });
  }, [all, model]);

  // Fallback: WC games that have already been played (if no upcoming exist yet)
  const playedWC = useMemo(() => {
    if (preds.length > 0) return [];
    return all.filter((p) => {
      const isWC = p.competition === "FIFA World Cup";
      const matchesModel = model === "" || p.model_version === model;
      return isWC && matchesModel;
    });
  }, [all, preds, model]);

  const noUpcoming = !loading && preds.length === 0;
  const displayPreds = preds.length > 0 ? preds : playedWC;
  const description = model ? MODEL_DESCRIPTIONS[model] : null;

  return (
    <main className="container mx-auto px-4 py-10 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">WC 2026 Predictions</h1>
        <p className="text-white/40 mt-1 text-sm">Model win probabilities for upcoming World Cup fixtures</p>
      </div>

      <div className="mb-6 space-y-3">
        <select
          value={model}
          onChange={(e) => setModel(e.target.value as ModelKey)}
          className="bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-white/25 appearance-none cursor-pointer"
        >
          {MODEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value} className="bg-neutral-900">{o.label}</option>
          ))}
        </select>

        {description && (
          <p className="text-white/45 text-sm leading-relaxed bg-white/5 border border-white/8 rounded-xl px-4 py-3 max-w-2xl">
            {description}
          </p>
        )}
      </div>

      {noUpcoming && (
        <div className="bg-amber-950/30 border border-amber-500/20 rounded-xl px-4 py-3 mb-6 flex items-start gap-3">
          <span className="text-amber-400 mt-0.5">⏳</span>
          <div>
            <p className="text-amber-300 text-sm font-medium">No upcoming fixtures yet</p>
            <p className="text-amber-400/60 text-xs mt-0.5">
              Upcoming WC 2026 matches appear here once loaded into the database.
              Showing most recent WC 2026 predictions below.
            </p>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-white/5 rounded-xl h-24 animate-pulse" />
          ))}
        </div>
      ) : displayPreds.length === 0 ? (
        <div className="text-center py-20 text-white/40">
          <p className="text-4xl mb-3">📊</p>
          <p>No WC 2026 predictions found.</p>
          <code className="mt-3 block text-xs text-white/25">python3.11 -m src.models.predict --model xgb_v1.0</code>
        </div>
      ) : (
        <div className="space-y-3">
          {displayPreds.map((p) => {
            const home = p.home_team_name ?? "Home";
            const away = p.away_team_name ?? "Away";
            return (
              <div
                key={p.pred_id}
                className="bg-white/5 border border-white/8 rounded-xl px-5 py-4 hover:bg-white/8 transition-colors"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3 flex-wrap">
                    <div className="flex items-center gap-1.5">
                      <span className="text-xl leading-none">{getFlag(home)}</span>
                      <span className="text-white/80 text-sm font-medium">{home}</span>
                    </div>
                    <span className="text-white/25 text-xs">vs</span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-xl leading-none">{getFlag(away)}</span>
                      <span className="text-white/80 text-sm font-medium">{away}</span>
                    </div>
                  </div>
                  <div className="text-right shrink-0 ml-2 space-y-1">
                    <span className="text-xs bg-white/10 text-white/50 rounded-full px-2 py-0.5 block">
                      {MODEL_DISPLAY[p.model_version] ?? p.model_version}
                    </span>
                    {p.match_date && (
                      <p className="text-white/25 text-xs">{p.match_date}</p>
                    )}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <ProbBar label={home} value={p.home_win_prob} color="bg-blue-500" />
                  <ProbBar label="Draw" value={p.draw_prob} color="bg-amber-500" />
                  <ProbBar label={away} value={p.away_win_prob} color="bg-red-500" />
                </div>
                {p.brier_score != null && (
                  <p className="text-white/20 text-xs mt-2 text-right">
                    Brier: {p.brier_score.toFixed(3)}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
