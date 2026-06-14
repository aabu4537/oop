"use client";

import { useState, useEffect, useRef } from "react";
import { searchPlayers, getPlayerMetrics, type Player, type PlayerMetric } from "@/lib/api";
import { getFlag } from "@/lib/flags";

const METRIC_LABELS: Record<string, string> = {
  press_intensity: "Press Intensity",
  run_frequency: "Run Frequency",
  space_creation_idx: "Space Creation",
  def_line_engagement: "Def. Line Engagement",
};

export default function PlayersPage() {
  const [query, setQuery] = useState("");
  const [players, setPlayers] = useState<Player[]>([]);
  const [selected, setSelected] = useState<Player | null>(null);
  const [metrics, setMetrics] = useState<PlayerMetric[]>([]);
  const [searching, setSearching] = useState(false);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 2) {
      setPlayers([]);
      return;
    }
    debounceRef.current = setTimeout(() => {
      setSearching(true);
      searchPlayers({ q: query.trim(), limit: 40 })
        .then(setPlayers)
        .finally(() => setSearching(false));
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  function selectPlayer(p: Player) {
    setSelected(p);
    setMetrics([]);
    setLoadingMetrics(true);
    getPlayerMetrics(p.player_id)
      .then(setMetrics)
      .finally(() => setLoadingMetrics(false));
  }

  return (
    <main className="container mx-auto px-4 py-10 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Player Metrics</h1>
        <p className="text-white/40 mt-1 text-sm">Off-ball movement metrics per match</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[320px_1fr] gap-6 items-start">
        {/* Left panel — search */}
        <div className="space-y-3">
          <div className="relative">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by player name…"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/25"
              autoFocus
            />
            {searching && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 text-xs">…</span>
            )}
          </div>

          {players.length > 0 && (
            <div className="rounded-xl border border-white/10 overflow-hidden">
              {players.map((p) => (
                <button
                  key={p.player_id}
                  onClick={() => selectPlayer(p)}
                  className={`w-full text-left px-4 py-3 flex items-center gap-3 border-b border-white/5 last:border-0 hover:bg-white/8 transition-colors ${
                    selected?.player_id === p.player_id ? "bg-white/10" : ""
                  }`}
                >
                  <span className="text-lg leading-none shrink-0">
                    {p.nationality ? getFlag(p.nationality) : "👤"}
                  </span>
                  <div className="min-w-0">
                    <p className="text-white/90 text-sm font-medium truncate">{p.name}</p>
                    <p className="text-white/35 text-xs truncate">
                      {p.team_name ?? "Unknown club"}
                      {p.position ? ` · ${p.position}` : ""}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}

          {query.trim().length >= 2 && !searching && players.length === 0 && (
            <p className="text-white/30 text-sm text-center py-4">No players found</p>
          )}

          {query.trim().length < 2 && (
            <p className="text-white/20 text-xs text-center py-2">Type at least 2 characters</p>
          )}
        </div>

        {/* Right panel — metrics */}
        <div>
          {!selected && (
            <div className="flex items-center justify-center h-48 text-white/25 text-sm">
              Select a player to view their metrics
            </div>
          )}

          {selected && (
            <>
              <div className="flex items-center gap-3 mb-5">
                <span className="text-3xl leading-none">
                  {selected.nationality ? getFlag(selected.nationality) : "👤"}
                </span>
                <div>
                  <h2 className="text-xl font-semibold text-white">{selected.name}</h2>
                  <p className="text-white/40 text-sm">
                    {selected.team_name ?? "Unknown club"}
                    {selected.position ? ` · ${selected.position}` : ""}
                  </p>
                </div>
              </div>

              {loadingMetrics ? (
                <div className="space-y-2">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="bg-white/5 rounded-lg h-10 animate-pulse" />
                  ))}
                </div>
              ) : metrics.length === 0 ? (
                <div className="text-center py-12 text-white/35">
                  <p className="text-3xl mb-2">📉</p>
                  <p className="text-sm">No match metrics found for this player.</p>
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-white/10">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-white/10 bg-white/5">
                        <th className="text-left px-4 py-3 text-white/40 font-medium text-xs">Match</th>
                        {Object.values(METRIC_LABELS).map((label) => (
                          <th key={label} className="text-right px-4 py-3 text-white/40 font-medium text-xs">
                            {label}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {metrics.map((m) => (
                        <tr key={m.metric_id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                          <td className="px-4 py-3 font-mono text-white/30 text-xs">
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
            </>
          )}
        </div>
      </div>
    </main>
  );
}
