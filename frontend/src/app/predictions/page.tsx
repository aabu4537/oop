"use client";

import { useEffect, useState } from "react";
import { getPredictions, type Prediction } from "@/lib/api";
import { getFlag } from "@/lib/flags";

const MODELS = ["", "xgb_v1.0", "lr_v1.0"];

function ProbBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-white/40 w-16 shrink-0">{label}</span>
      <div className="flex-1 bg-white/10 rounded-full h-1.5 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value * 100}%` }} />
      </div>
      <span className="text-white/60 tabular-nums w-10 text-right">{(value * 100).toFixed(1)}%</span>
    </div>
  );
}

export default function PredictionsPage() {
  const [preds, setPreds] = useState<Prediction[]>([]);
  const [model, setModel] = useState("");
  const [loading, setLoading] = useState(true);

  function load(mv: string) {
    setLoading(true);
    getPredictions(mv || undefined)
      .then(setPreds)
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(""); }, []);

  return (
    <main className="container mx-auto px-4 py-10 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Predictions</h1>
        <p className="text-white/40 mt-1 text-sm">Win probabilities from trained models</p>
      </div>

      <div className="flex gap-3 mb-8">
        <select
          value={model}
          onChange={(e) => { setModel(e.target.value); load(e.target.value); }}
          className="bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:border-white/25 appearance-none cursor-pointer"
        >
          {MODELS.map((m) => (
            <option key={m} value={m} className="bg-neutral-900">{m || "All models"}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-white/5 rounded-xl h-24 animate-pulse" />
          ))}
        </div>
      ) : preds.length === 0 ? (
        <div className="text-center py-20 text-white/40">
          <p className="text-4xl mb-3">📊</p>
          <p>No predictions found. Run the modeling pipeline first.</p>
          <code className="mt-3 block text-xs text-white/25">python3.11 -m src.models.predict</code>
        </div>
      ) : (
        <div className="space-y-3">
          {preds.map((p) => {
            const home = p.home_team_name ?? "Home";
            const away = p.away_team_name ?? "Away";
            return (
              <div
                key={p.pred_id}
                className="bg-white/5 border border-white/8 rounded-xl px-5 py-4 hover:bg-white/8 transition-colors"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
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
                  <div className="text-right shrink-0">
                    <span className="text-xs bg-white/10 text-white/50 rounded-full px-2 py-0.5">
                      {p.model_version}
                    </span>
                    {p.match_date && (
                      <p className="text-white/25 text-xs mt-1">{p.match_date}</p>
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
