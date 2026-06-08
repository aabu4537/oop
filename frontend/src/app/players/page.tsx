"use client";

import { useState } from "react";
import { getPlayerMetrics, type PlayerMetric } from "@/lib/api";

const METRIC_LABELS: Record<string, string> = {
  press_intensity: "Press Intensity",
  run_frequency: "Run Frequency",
  space_creation_idx: "Space Creation",
  def_line_engagement: "Def. Line Engagement",
};

export default function PlayersPage() {
  const [playerId, setPlayerId] = useState("");
  const [metrics, setMetrics] = useState<PlayerMetric[]>([]);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState(false);

  function search() {
    if (!playerId.trim()) return;
    setLoading(true);
    setSearched(true);
    getPlayerMetrics(playerId.trim())
      .then(setMetrics)
      .finally(() => setLoading(false));
  }

  return (
    <main className="container mx-auto px-4 py-10 max-w-4xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Player Metrics</h1>
        <p className="text-white/40 mt-1 text-sm">Off-ball metrics per match</p>
      </div>

      <div className="flex gap-3 mb-8">
        <input
          value={playerId}
          onChange={(e) => setPlayerId(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="Player UUID (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)"
          className="flex-1 bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/25 font-mono"
        />
        <button
          onClick={search}
          disabled={!playerId.trim() || loading}
          className="px-5 py-2.5 bg-white text-black rounded-lg text-sm font-semibold hover:bg-white/90 disabled:opacity-40 transition-colors"
        >
          {loading ? "…" : "Search"}
        </button>
      </div>

      {searched && !loading && metrics.length === 0 && (
        <div className="text-center py-20 text-white/40">
          <p className="text-4xl mb-3">👤</p>
          <p>No metrics found for this player UUID.</p>
        </div>
      )}

      {metrics.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-3 text-white/50 font-medium text-xs">Match</th>
                {Object.values(METRIC_LABELS).map((label) => (
                  <th key={label} className="text-right px-4 py-3 text-white/50 font-medium text-xs">
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr
                  key={m.metric_id}
                  className="border-b border-white/5 hover:bg-white/5 transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-white/40 text-xs">
                    {m.match_id?.slice(0, 8)}…
                  </td>
                  {Object.keys(METRIC_LABELS).map((key) => {
                    const val = m[key as keyof PlayerMetric] as number | null;
                    return (
                      <td key={key} className="px-4 py-3 text-right tabular-nums">
                        {val != null ? (
                          <span className="text-emerald-400">{val.toFixed(3)}</span>
                        ) : (
                          <span className="text-white/20">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
