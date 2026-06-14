"use client";

import { useState } from "react";
import { simulate, type SimulateResponse } from "@/lib/api";
import { getFlag } from "@/lib/flags";

// ── WC 2026 confirmed draw — Elo from live DB ────────────────────────────────
// Names match the DB exactly so the simulation engine resolves them correctly.

type TeamEntry = { name: string; elo: number };

const WC2026_GROUPS: Record<string, TeamEntry[]> = {
  A: [{ name: "Mexico", elo: 1789 }, { name: "South Korea", elo: 1768 }, { name: "South Africa", elo: 1606 }, { name: "Czechia", elo: 1573 }],
  B: [{ name: "Canada", elo: 1711 }, { name: "Switzerland", elo: 1814 }, { name: "Qatar", elo: 1476 }, { name: "Bosnia and Herzegovina", elo: 1498 }],
  C: [{ name: "Brazil", elo: 1845 }, { name: "Morocco", elo: 1864 }, { name: "Scotland", elo: 1641 }, { name: "Haiti", elo: 1629 }],
  D: [{ name: "USA", elo: 1668 }, { name: "Australia", elo: 1762 }, { name: "Paraguay", elo: 1623 }, { name: "Türkiye", elo: 1856 }],
  E: [{ name: "Germany", elo: 1840 }, { name: "Ecuador", elo: 1815 }, { name: "Ivory Coast", elo: 1765 }, { name: "Curaçao", elo: 1530 }],
  F: [{ name: "Netherlands", elo: 1822 }, { name: "Japan", elo: 1832 }, { name: "Tunisia", elo: 1656 }, { name: "Sweden", elo: 1595 }],
  G: [{ name: "Belgium", elo: 1770 }, { name: "Iran", elo: 1771 }, { name: "Egypt", elo: 1729 }, { name: "New Zealand", elo: 1591 }],
  H: [{ name: "Spain", elo: 2032 }, { name: "Uruguay", elo: 1741 }, { name: "Saudi Arabia", elo: 1600 }, { name: "Cabo Verde", elo: 1604 }],
  I: [{ name: "France", elo: 1940 }, { name: "Senegal", elo: 1839 }, { name: "Norway", elo: 1811 }, { name: "Iraq", elo: 1646 }],
  J: [{ name: "Argentina", elo: 1962 }, { name: "Austria", elo: 1742 }, { name: "Algeria", elo: 1808 }, { name: "Jordan", elo: 1646 }],
  K: [{ name: "Portugal", elo: 1842 }, { name: "Colombia", elo: 1838 }, { name: "Uzbekistan", elo: 1689 }, { name: "DR Congo", elo: 1668 }],
  L: [{ name: "England", elo: 1919 }, { name: "Croatia", elo: 1758 }, { name: "Panama", elo: 1692 }, { name: "Ghana", elo: 1526 }],
};

const STAGE_ORDER = ["group_stage", "round_of_32", "round_of_16", "quarter_final", "semi_final", "final", "champion"];
const STAGE_LABELS: Record<string, string> = {
  group_stage: "Groups",
  round_of_32: "R32",
  round_of_16: "R16",
  quarter_final: "QF",
  semi_final: "SF",
  final: "Final",
  champion: "🏆",
};

function probBg(p: number): string {
  if (p >= 0.5) return "bg-emerald-500/40 text-emerald-300";
  if (p >= 0.25) return "bg-emerald-700/30 text-emerald-400";
  if (p >= 0.1) return "bg-white/8 text-white/60";
  return "text-white/20";
}

function ResultsTable({ result }: { result: SimulateResponse }) {
  const allKeys = Object.keys(result.results[0]).filter((k) => k !== "team" && k !== "elo");
  const stageKeys = STAGE_ORDER.filter((k) => allKeys.includes(k));
  const sorted = [...result.results].sort((a, b) => (b.champion as number) - (a.champion as number));

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Simulation Results</h2>
        <span className="text-white/30 text-xs">{result.n_sims.toLocaleString()} simulations</span>
      </div>
      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 bg-white/5">
              <th className="text-left px-3 py-3 text-white/40 font-medium text-xs w-8">#</th>
              <th className="text-left px-4 py-3 text-white/40 font-medium text-xs">Team</th>
              {stageKeys.map((k) => (
                <th key={k} className="text-center px-3 py-3 text-white/40 font-medium text-xs">
                  {STAGE_LABELS[k] ?? k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row, i) => {
              const name = row.team as string;
              return (
                <tr key={name} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                  <td className="px-3 py-2.5 text-white/20 text-xs tabular-nums">{i + 1}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="text-base leading-none">{getFlag(name)}</span>
                      <span className="text-white/80 text-sm">{name}</span>
                    </div>
                  </td>
                  {stageKeys.map((k) => {
                    const p = row[k] as number;
                    return (
                      <td key={k} className={`px-3 py-2.5 text-center tabular-nums text-xs font-medium ${probBg(p)}`}>
                        {(p * 100).toFixed(1)}%
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function GroupsPage() {
  const [nSims, setNSims] = useState(10_000);
  const [seed, setSeed] = useState(42);
  const [result, setResult] = useState<SimulateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function runSim() {
    setLoading(true);
    setError("");
    try {
      const res = await simulate({ groups: WC2026_GROUPS, n_sims: nSims, seed });
      setResult(res);
    } catch (err) {
      if (err instanceof TypeError && err.message.includes("fetch")) {
        setError(
          "Could not connect to simulation API. Make sure the backend is running with: python3.11 -m uvicorn src.api.main:app --reload"
        );
      } else {
        setError(`Simulation error: ${err instanceof Error ? err.message : String(err)}`);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="container mx-auto px-4 py-10 max-w-7xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">WC 2026 Groups</h1>
        <p className="text-white/40 mt-1 text-sm">Confirmed draw · 12 groups · 48 teams</p>
      </div>

      {/* Groups grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3 mb-10">
        {Object.entries(WC2026_GROUPS).map(([letter, teams]) => (
          <div key={letter} className="bg-white/5 border border-white/8 rounded-xl p-4">
            <p className="text-white/30 text-xs font-semibold uppercase tracking-widest mb-3">
              Group {letter}
            </p>
            <div className="space-y-2">
              {teams.map((t) => (
                <div key={t.name} className="flex items-center gap-2">
                  <span className="text-base leading-none shrink-0">{getFlag(t.name)}</span>
                  <span className="text-white/75 text-xs truncate">{t.name}</span>
                  <span className="text-white/20 text-xs tabular-nums ml-auto">{t.elo}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Simulation controls */}
      <div className="bg-white/5 border border-white/8 rounded-xl p-5 mb-8">
        <h2 className="text-sm font-medium text-white mb-4">Monte Carlo Simulation</h2>
        <div className="flex flex-wrap items-end gap-6">
          <div className="flex-1 min-w-48">
            <label className="text-white/40 text-xs font-medium block mb-2">
              Simulations: <span className="text-white">{nSims.toLocaleString()}</span>
            </label>
            <input
              type="range"
              min={1000}
              max={50000}
              step={1000}
              value={nSims}
              onChange={(e) => setNSims(Number(e.target.value))}
              className="w-full accent-emerald-500"
            />
          </div>
          <div>
            <label className="text-white/40 text-xs font-medium block mb-2">Seed</label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
              className="w-24 bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm text-white tabular-nums focus:outline-none focus:border-white/25"
            />
          </div>
          <button
            onClick={runSim}
            disabled={loading}
            className="flex items-center gap-2 px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors"
          >
            {loading ? (
              <>
                <span className="inline-block w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Simulating…
              </>
            ) : (
              "Run Simulation"
            )}
          </button>
        </div>
        <p className="text-white/25 text-xs mt-3">
          Poisson goal model · Live Elo + OOP composites from DB · {nSims.toLocaleString()} Monte Carlo runs
        </p>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-500/30 rounded-xl px-4 py-3 mb-6">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {loading && !result && (
        <div className="flex items-center justify-center py-16 gap-3 text-white/40">
          <span className="inline-block w-5 h-5 border-2 border-white/20 border-t-white/60 rounded-full animate-spin" />
          <span className="text-sm">Running {nSims.toLocaleString()} simulations…</span>
        </div>
      )}

      {result && !loading && <ResultsTable result={result} />}
    </main>
  );
}
