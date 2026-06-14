"use client";

import { useState, useEffect, useRef, useMemo } from "react";
import { searchPlayers, getPlayerMetrics, getMatches, type Player, type PlayerMetric, type Match } from "@/lib/api";
import { getFlag } from "@/lib/flags";

// ── Code → full name map ──────────────────────────────────────────────────────

const CODE_TO_NAME: Record<string, string> = {
  ESP: "Spain", ENG: "England", FRA: "France", GER: "Germany",
  BRA: "Brazil", ARG: "Argentina", POR: "Portugal", NED: "Netherlands",
  BEL: "Belgium", URU: "Uruguay", SEN: "Senegal", MAR: "Morocco",
  JPN: "Japan", KOR: "South Korea", MEX: "Mexico", USA: "United States",
  CAN: "Canada", AUS: "Australia", CRO: "Croatia", SUI: "Switzerland",
  DEN: "Denmark", SRB: "Serbia", COL: "Colombia", ECU: "Ecuador",
  IRN: "Iran", TUN: "Tunisia", EGY: "Egypt", NGA: "Nigeria",
  CMR: "Cameroon", GHA: "Ghana", SAU: "Saudi Arabia", QAT: "Qatar",
  ALG: "Algeria", CIV: "Ivory Coast", NOR: "Norway", SWE: "Sweden",
  AUT: "Austria", UZB: "Uzbekistan", JOR: "Jordan", PAR: "Paraguay",
  TUR: "Türkiye", SCO: "Scotland", HAI: "Haiti", CPV: "Cabo Verde",
  CUW: "Curaçao", IRQ: "Iraq", BIH: "Bosnia and Herzegovina",
  ZAF: "South Africa", CZE: "Czechia", COD: "DR Congo", NZL: "New Zealand",
};

function resolveName(raw: string | null | undefined): string {
  if (!raw) return "?";
  return CODE_TO_NAME[raw] ?? raw;
}

function formatMatchDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// ── OOP scoring ───────────────────────────────────────────────────────────────
// Calibrated to global DB ranges (0→max from actual data):
//   press_intensity 0→71, def_line_engagement 0→26.8,
//   interceptions_per90 0→11.5, ball_recoveries_per90 0→18.4,
//   pressure_final_third_pct 0→1 (proportion, not %)

const OOP_WEIGHTS = {
  press_intensity: 0.30,
  def_line_engagement: 0.25,
  pressure_final_third_pct: 0.20,
  interceptions_per90: 0.15,
  ball_recoveries_per90: 0.10,
} as const;

const GLOBAL_MAX: Record<keyof typeof OOP_WEIGHTS, number> = {
  press_intensity: 71,
  def_line_engagement: 27,
  pressure_final_third_pct: 1,
  interceptions_per90: 12,
  ball_recoveries_per90: 19,
};

type OopKey = keyof typeof OOP_WEIGHTS;

interface OopResult {
  score: number;       // 0-100 globally calibrated composite
  grade: string;
  color: string;
  breakdown: Record<OopKey, { raw: number | null; pct: number; contribution: number }>;
}

function computeOop(metric: PlayerMetric): OopResult {
  const breakdown = {} as OopResult["breakdown"];
  let score = 0;

  for (const [key, weight] of Object.entries(OOP_WEIGHTS) as [OopKey, number][]) {
    const raw = metric[key] as number | null;
    const pct = raw != null ? Math.min((raw / GLOBAL_MAX[key]) * 100, 100) : 0;
    const contribution = pct * weight;
    breakdown[key] = { raw, pct, contribution };
    score += contribution;
  }

  return { score, ...gradeFromScore(score), breakdown };
}

// Percentile-style thresholds based on realistic distribution
function gradeFromScore(score: number): { grade: string; color: string } {
  if (score >= 65) return { grade: "A+", color: "text-emerald-400" };
  if (score >= 50) return { grade: "A",  color: "text-emerald-400" };
  if (score >= 35) return { grade: "B",  color: "text-blue-400" };
  if (score >= 22) return { grade: "C",  color: "text-amber-400" };
  if (score >= 12) return { grade: "D",  color: "text-orange-400" };
  return           { grade: "F",  color: "text-red-400" };
}

// EWMA overall score (span=10 → alpha=2/11)
const EWMA_ALPHA = 2 / 11;

function computeOverall(metrics: PlayerMetric[]): { overall: number; matchCount: number } {
  if (metrics.length === 0) return { overall: 0, matchCount: 0 };
  // compute raw score per metric, then EWMA
  const scores = metrics.map((m) => computeOop(m).score);
  let ewma = scores[0];
  for (let i = 1; i < scores.length; i++) {
    ewma = EWMA_ALPHA * scores[i] + (1 - EWMA_ALPHA) * ewma;
  }
  return { overall: ewma, matchCount: metrics.length };
}

const OOP_KEY_LABELS: Record<OopKey, string> = {
  press_intensity: "Press Intensity",
  def_line_engagement: "Def. Line Engagement",
  pressure_final_third_pct: "Press Final Third",
  interceptions_per90: "Interceptions / 90",
  ball_recoveries_per90: "Ball Recoveries / 90",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function GradeBadge({ grade, color, score }: { grade: string; color: string; score: number }) {
  return (
    <span className={`font-bold tabular-nums ${color}`}>
      {score.toFixed(1)}{" "}
      <span className="text-xs opacity-70">{grade}</span>
    </span>
  );
}

const BASE_METRIC_KEYS = ["press_intensity", "run_frequency", "space_creation_idx", "def_line_engagement"] as const;
const BASE_METRIC_LABELS: Record<string, string> = {
  press_intensity: "Press",
  run_frequency: "Run Freq.",
  space_creation_idx: "Space",
  def_line_engagement: "Def. Line",
};

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PlayersPage() {
  const [query, setQuery] = useState("");
  const [players, setPlayers] = useState<Player[]>([]);
  const [selected, setSelected] = useState<Player | null>(null);
  const [metrics, setMetrics] = useState<PlayerMetric[]>([]);
  const [matchMap, setMatchMap] = useState<Map<string, Match>>(new Map());
  const [searching, setSearching] = useState(false);
  const [loadingMetrics, setLoadingMetrics] = useState(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [sortByOop, setSortByOop] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load all matches once for match context lookup
  useEffect(() => {
    getMatches({ limit: 2000 }).then((ms) => {
      setMatchMap(new Map(ms.map((m) => [m.match_id, m])));
    });
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 2) { setPlayers([]); return; }
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
    getPlayerMetrics(p.player_id).then(setMetrics).finally(() => setLoadingMetrics(false));
  }

  const { overall, matchCount } = useMemo(() => computeOverall(metrics), [metrics]);

  const displayMetrics = useMemo(() => {
    const rows = metrics.map((m) => ({ m, oop: computeOop(m) }));
    if (sortByOop) rows.sort((a, b) => b.oop.score - a.oop.score);
    return rows;
  }, [metrics, sortByOop]);

  const overallOop = gradeFromScore(overall);

  return (
    <main className="container mx-auto px-4 py-10 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Player Metrics</h1>
        <p className="text-white/40 mt-1 text-sm">Off-ball movement metrics · OOP composite rating</p>
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
                      {p.team_name ?? "Unknown club"}{p.position ? ` · ${p.position}` : ""}
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
              {/* Player header */}
              <div className="flex items-center justify-between mb-5 flex-wrap gap-3">
                <div className="flex items-center gap-3">
                  <span className="text-3xl leading-none">
                    {selected.nationality ? getFlag(selected.nationality) : "👤"}
                  </span>
                  <div>
                    <h2 className="text-xl font-semibold text-white">{selected.name}</h2>
                    <p className="text-white/40 text-sm">
                      {selected.team_name ?? "Unknown club"}{selected.position ? ` · ${selected.position}` : ""}
                    </p>
                  </div>
                </div>
                {metrics.length > 0 && (
                  <div className="flex items-center gap-3">
                    {/* Overall score card */}
                    <div className="bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-center min-w-28">
                      <p className="text-white/35 text-xs mb-0.5">Overall</p>
                      <p className={`text-lg font-bold tabular-nums ${overallOop.color}`}>
                        {overall.toFixed(1)}
                        <span className="text-xs ml-1 opacity-70">{overallOop.grade}</span>
                      </p>
                      <p className="text-white/20 text-xs">across {matchCount} match{matchCount !== 1 ? "es" : ""}</p>
                    </div>
                    <button
                      onClick={() => setSortByOop((s) => !s)}
                      className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                        sortByOop
                          ? "bg-emerald-600/30 border-emerald-500/40 text-emerald-300"
                          : "bg-white/5 border-white/10 text-white/50 hover:text-white"
                      }`}
                    >
                      Sort by OOP
                    </button>
                  </div>
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
                        <th className="text-left px-4 py-3 text-white/40 font-medium text-xs min-w-52">Match</th>
                        {BASE_METRIC_KEYS.map((key) => (
                          <th key={key} className="text-right px-3 py-3 text-white/40 font-medium text-xs">
                            {BASE_METRIC_LABELS[key]}
                          </th>
                        ))}
                        <th className="text-right px-4 py-3 text-emerald-400/70 font-medium text-xs">OOP Rating</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayMetrics.map(({ m, oop }) => {
                        const match = m.match_id ? matchMap.get(m.match_id) : null;
                        const home = resolveName(match?.home_team_name);
                        const away = resolveName(match?.away_team_name);
                        const matchLabel = match
                          ? `${home} vs ${away}`
                          : (m.match_id?.slice(0, 8) ?? "?") + "…";
                        const dateLabel = match?.match_date ? formatMatchDate(match.match_date) : "";
                        const compLabel = match?.competition ?? "";

                        return (
                          <>
                            <tr
                              key={m.metric_id}
                              onClick={() => setExpandedRow(expandedRow === m.metric_id ? null : m.metric_id)}
                              className="border-b border-white/5 hover:bg-white/5 transition-colors cursor-pointer"
                            >
                              <td className="px-4 py-3">
                                <p className="text-white/70 text-xs font-medium">{matchLabel}</p>
                                {(dateLabel || compLabel) && (
                                  <p className="text-white/25 text-xs mt-0.5">
                                    {[dateLabel, compLabel].filter(Boolean).join(" · ")}
                                  </p>
                                )}
                              </td>
                              {BASE_METRIC_KEYS.map((key) => {
                                const val = m[key] as number | null;
                                return (
                                  <td key={key} className="px-3 py-3 text-right tabular-nums">
                                    {val != null
                                      ? <span className="text-white/60 text-xs">{val.toFixed(2)}</span>
                                      : <span className="text-white/20">—</span>}
                                  </td>
                                );
                              })}
                              <td className="px-4 py-3 text-right">
                                <GradeBadge grade={oop.grade} color={oop.color} score={oop.score} />
                              </td>
                            </tr>
                            {expandedRow === m.metric_id && (
                              <tr key={`${m.metric_id}-expand`} className="border-b border-white/5 bg-white/[0.02]">
                                <td colSpan={BASE_METRIC_KEYS.length + 2} className="px-4 py-3">
                                  <p className="text-white/35 text-xs font-medium mb-2 uppercase tracking-wide">
                                    OOP Breakdown
                                  </p>
                                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                                    {(Object.entries(oop.breakdown) as [OopKey, OopResult["breakdown"][OopKey]][]).map(
                                      ([key, { raw, pct, contribution }]) => (
                                        <div key={key} className="bg-white/5 rounded-lg px-3 py-2">
                                          <p className="text-white/30 text-xs mb-1">{OOP_KEY_LABELS[key]}</p>
                                          <div className="flex items-baseline gap-1 flex-wrap">
                                            <span className="text-white/60 text-xs tabular-nums">
                                              {raw != null ? raw.toFixed(2) : "—"}
                                            </span>
                                            <span className="text-emerald-400 text-xs tabular-nums ml-auto">
                                              +{contribution.toFixed(1)}
                                            </span>
                                          </div>
                                          <div className="mt-1.5 bg-white/10 rounded-full h-1 overflow-hidden">
                                            <div
                                              className="h-full bg-emerald-500 rounded-full"
                                              style={{ width: `${pct}%` }}
                                            />
                                          </div>
                                          <p className="text-white/20 text-xs mt-1">
                                            {pct.toFixed(0)}% · {(OOP_WEIGHTS[key] * 100).toFixed(0)}% wt
                                          </p>
                                        </div>
                                      )
                                    )}
                                  </div>
                                </td>
                              </tr>
                            )}
                          </>
                        );
                      })}
                    </tbody>
                  </table>
                  <p className="text-white/15 text-xs px-4 py-2 border-t border-white/5">
                    Click any row to expand OOP breakdown · Overall score uses EWMA (span=10) weighting recent matches higher
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
