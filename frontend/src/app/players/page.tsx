"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { searchPlayers, getPlayerMetrics, type Player, type PlayerMetric } from "@/lib/api";
import { getFlag } from "@/lib/flags";

// ── OOP composite helpers ────────────────────────────────────────────────────

const OOP_WEIGHTS = {
  press_intensity: 0.30,
  pressure_final_third_pct: 0.20,
  interceptions_per90: 0.15,
  ball_recoveries_per90: 0.10,
  // pressure_success_rate not in schema; substitute def_line_engagement
  def_line_engagement: 0.25,
} as const;

type OopKey = keyof typeof OOP_WEIGHTS;

function minMax(vals: number[]): { min: number; max: number } {
  if (vals.length === 0) return { min: 0, max: 1 };
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  return { min, max: max === min ? min + 1 : max };
}

interface OopResult {
  score: number;
  grade: string;
  color: string;
  breakdown: Record<OopKey, { raw: number | null; normalized: number; contribution: number }>;
}

function computeOop(metric: PlayerMetric, ranges: Record<OopKey, { min: number; max: number }>): OopResult {
  const breakdown = {} as OopResult["breakdown"];
  let score = 0;

  for (const [key, weight] of Object.entries(OOP_WEIGHTS) as [OopKey, number][]) {
    const raw = metric[key] as number | null;
    const { min, max } = ranges[key];
    const normalized = raw != null ? ((raw - min) / (max - min)) * 100 : 0;
    const contribution = normalized * weight;
    breakdown[key] = { raw, normalized, contribution };
    score += contribution;
  }

  let grade: string;
  let color: string;
  if (score >= 90) { grade = "A+"; color = "text-emerald-400"; }
  else if (score >= 80) { grade = "A"; color = "text-emerald-400"; }
  else if (score >= 70) { grade = "B"; color = "text-blue-400"; }
  else if (score >= 60) { grade = "C"; color = "text-amber-400"; }
  else if (score >= 50) { grade = "D"; color = "text-orange-400"; }
  else { grade = "F"; color = "text-red-400"; }

  return { score, grade, color, breakdown };
}

function buildRanges(metrics: PlayerMetric[]): Record<OopKey, { min: number; max: number }> {
  const ranges = {} as Record<OopKey, { min: number; max: number }>;
  for (const key of Object.keys(OOP_WEIGHTS) as OopKey[]) {
    const vals = metrics.map((m) => m[key] as number | null).filter((v): v is number => v != null);
    ranges[key] = minMax(vals);
  }
  return ranges;
}

const OOP_KEY_LABELS: Record<OopKey, string> = {
  press_intensity: "Press Intensity",
  def_line_engagement: "Def. Line Engagement",
  pressure_final_third_pct: "Press Final Third %",
  interceptions_per90: "Interceptions / 90",
  ball_recoveries_per90: "Ball Recoveries / 90",
};

// ── Badge helpers ────────────────────────────────────────────────────────────

function GradeBadge({ grade, color, score }: { grade: string; color: string; score: number }) {
  return (
    <span className={`font-bold tabular-nums ${color}`}>
      {score.toFixed(1)}{" "}
      <span className="text-xs opacity-70">{grade}</span>
    </span>
  );
}

// ── Table columns besides OOP ────────────────────────────────────────────────

const BASE_METRIC_KEYS = [
  "press_intensity",
  "run_frequency",
  "space_creation_idx",
  "def_line_engagement",
] as const;

const BASE_METRIC_LABELS: Record<string, string> = {
  press_intensity: "Press Intensity",
  run_frequency: "Run Freq.",
  space_creation_idx: "Space Creation",
  def_line_engagement: "Def. Line Eng.",
};

// ── Main page ────────────────────────────────────────────────────────────────

export default function PlayersPage() {
  const [query, setQuery] = useState("");
  const [players, setPlayers] = useState<Player[]>([]);
  const [selected, setSelected] = useState<Player | null>(null);
  const [metrics, setMetrics] = useState<PlayerMetric[]>([]);
  const [searching, setSearching] = useState(false);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [sortByOop, setSortByOop] = useState(false);
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
    setExpandedRow(null);
    setSortByOop(false);
    setLoadingMetrics(true);
    getPlayerMetrics(p.player_id)
      .then(setMetrics)
      .finally(() => setLoadingMetrics(false));
  }

  // Build per-player ranges from all their metrics for normalization
  const ranges = useMemo(() => buildRanges(metrics), [metrics]);

  const displayMetrics = useMemo(() => {
    const withOop = metrics.map((m) => ({ m, oop: computeOop(m, ranges) }));
    if (sortByOop) withOop.sort((a, b) => b.oop.score - a.oop.score);
    return withOop;
  }, [metrics, ranges, sortByOop]);

  return (
    <main className="container mx-auto px-4 py-10 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Player Metrics</h1>
        <p className="text-white/40 mt-1 text-sm">Off-ball movement metrics per match</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[300px_1fr] gap-6 items-start">
        {/* Left — search */}
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
            <div className="rounded-xl border border-white/10 overflow-hidden max-h-[60vh] overflow-y-auto">
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

        {/* Right — metrics */}
        <div>
          {!selected && (
            <div className="flex items-center justify-center h-48 text-white/25 text-sm">
              Select a player to view their metrics
            </div>
          )}

          {selected && (
            <>
              <div className="flex items-center justify-between mb-5">
                <div className="flex items-center gap-3">
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
                {metrics.length > 0 && (
                  <button
                    onClick={() => setSortByOop((s) => !s)}
                    className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                      sortByOop
                        ? "bg-emerald-600/30 border-emerald-500/40 text-emerald-300"
                        : "bg-white/5 border-white/10 text-white/50 hover:text-white"
                    }`}
                  >
                    Sort by OOP Rating
                  </button>
                )}
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
                        {BASE_METRIC_KEYS.map((key) => (
                          <th key={key} className="text-right px-3 py-3 text-white/40 font-medium text-xs">
                            {BASE_METRIC_LABELS[key]}
                          </th>
                        ))}
                        <th className="text-right px-4 py-3 text-emerald-400/70 font-medium text-xs">
                          OOP Rating
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayMetrics.map(({ m, oop }) => (
                        <>
                          <tr
                            key={m.metric_id}
                            onClick={() => setExpandedRow(expandedRow === m.metric_id ? null : m.metric_id)}
                            className="border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                          >
                            <td className="px-4 py-3 font-mono text-white/30 text-xs">
                              {m.match_id?.slice(0, 8)}…
                            </td>
                            {BASE_METRIC_KEYS.map((key) => {
                              const val = m[key] as number | null;
                              return (
                                <td key={key} className="px-3 py-3 text-right tabular-nums">
                                  {val != null ? (
                                    <span className="text-white/60">{val.toFixed(2)}</span>
                                  ) : (
                                    <span className="text-white/20">—</span>
                                  )}
                                </td>
                              );
                            })}
                            <td className="px-4 py-3 text-right">
                              <GradeBadge grade={oop.grade} color={oop.color} score={oop.score} />
                            </td>
                          </tr>
                          {expandedRow === m.metric_id && (
                            <tr key={`${m.metric_id}-expand`} className="border-b border-white/5 bg-white/3">
                              <td colSpan={BASE_METRIC_KEYS.length + 2} className="px-4 py-3">
                                <p className="text-white/40 text-xs font-medium mb-2 uppercase tracking-wide">
                                  OOP Breakdown
                                </p>
                                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                                  {(Object.entries(oop.breakdown) as [OopKey, OopResult["breakdown"][OopKey]][]).map(
                                    ([key, { raw, normalized, contribution }]) => (
                                      <div key={key} className="bg-white/5 rounded-lg px-3 py-2">
                                        <p className="text-white/35 text-xs mb-1">{OOP_KEY_LABELS[key]}</p>
                                        <div className="flex items-baseline gap-1.5">
                                          <span className="text-white/70 text-xs tabular-nums">
                                            {raw != null ? raw.toFixed(2) : "—"}
                                          </span>
                                          <span className="text-white/25 text-xs">→</span>
                                          <span className="text-emerald-400 text-xs tabular-nums">
                                            +{contribution.toFixed(1)}
                                          </span>
                                          <span className="text-white/20 text-xs">
                                            ({(OOP_WEIGHTS[key] * 100).toFixed(0)}% weight)
                                          </span>
                                        </div>
                                        <div className="mt-1.5 bg-white/10 rounded-full h-1 overflow-hidden">
                                          <div
                                            className="h-full bg-emerald-500 rounded-full"
                                            style={{ width: `${Math.min(normalized, 100)}%` }}
                                          />
                                        </div>
                                      </div>
                                    )
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      ))}
                    </tbody>
                  </table>
                  <p className="text-white/20 text-xs px-4 py-2 border-t border-white/5">
                    Click any row to see OOP breakdown · Scores normalized relative to this player&apos;s matches
                  </p>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
