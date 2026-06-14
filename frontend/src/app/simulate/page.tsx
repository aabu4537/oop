"use client";

import { useState } from "react";
import { simulate, simulateWC2026, type SimulateResponse } from "@/lib/api";
import { getFlag } from "@/lib/flags";

type TeamEntry = { name: string; elo: number };
type Groups = Record<string, TeamEntry[]>;

// WC 2026 confirmed draw — 12 groups, 48 teams
const WC2026_GROUPS: Groups = {
  A: [{ name: "Mexico", elo: 1789 }, { name: "South Korea", elo: 1768 }, { name: "South Africa", elo: 1520 }, { name: "Czechia", elo: 1680 }],
  B: [{ name: "Canada", elo: 1738 }, { name: "Switzerland", elo: 1804 }, { name: "Qatar", elo: 1621 }, { name: "Bosnia and Herzegovina", elo: 1610 }],
  C: [{ name: "Brazil", elo: 1845 }, { name: "Morocco", elo: 1864 }, { name: "Scotland", elo: 1650 }, { name: "Haiti", elo: 1430 }],
  D: [{ name: "USA", elo: 1632 }, { name: "Australia", elo: 1762 }, { name: "Paraguay", elo: 1620 }, { name: "Türkiye", elo: 1700 }],
  E: [{ name: "Germany", elo: 1840 }, { name: "Ecuador", elo: 1815 }, { name: "Ivory Coast", elo: 1710 }, { name: "Curaçao", elo: 1350 }],
  F: [{ name: "Netherlands", elo: 1822 }, { name: "Japan", elo: 1832 }, { name: "Tunisia", elo: 1679 }, { name: "Sweden", elo: 1730 }],
  G: [{ name: "Belgium", elo: 1770 }, { name: "Iran", elo: 1771 }, { name: "Egypt", elo: 1650 }, { name: "New Zealand", elo: 1480 }],
  H: [{ name: "Spain", elo: 2032 }, { name: "Uruguay", elo: 1790 }, { name: "Saudi Arabia", elo: 1621 }, { name: "Cabo Verde", elo: 1490 }],
  I: [{ name: "France", elo: 1940 }, { name: "Senegal", elo: 1839 }, { name: "Norway", elo: 1750 }, { name: "Iraq", elo: 1560 }],
  J: [{ name: "Argentina", elo: 1962 }, { name: "Austria", elo: 1710 }, { name: "Algeria", elo: 1660 }, { name: "Jordan", elo: 1510 }],
  K: [{ name: "Portugal", elo: 1842 }, { name: "Colombia", elo: 1838 }, { name: "Uzbekistan", elo: 1540 }, { name: "DR Congo", elo: 1580 }],
  L: [{ name: "England", elo: 1919 }, { name: "Croatia", elo: 1758 }, { name: "Panama", elo: 1560 }, { name: "Ghana", elo: 1541 }],
};

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
  return "text-white/25";
}

function ResultsTable({ result }: { result: SimulateResponse }) {
  const stageKeys = Object.keys(result.results[0]).filter((k) => k !== "team" && k !== "elo");
  const sorted = [...result.results].sort(
    (a, b) => (b.champion as number) - (a.champion as number)
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Results</h2>
        <span className="text-white/30 text-xs">{result.n_sims.toLocaleString()} simulations</span>
      </div>
      <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 bg-white/5">
              <th className="text-left px-4 py-3 text-white/50 font-medium text-xs">Team</th>
              {stageKeys.map((k) => (
                <th key={k} className="text-center px-3 py-3 text-white/50 font-medium text-xs">
                  {STAGE_LABELS[k] ?? k}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => {
              const name = row.team as string;
              return (
                <tr key={name} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2">
                      <span className="text-lg leading-none">{getFlag(name)}</span>
                      <span className="text-white/80 text-sm">{name}</span>
                    </div>
                  </td>
                  {stageKeys.map((k) => {
                    const p = row[k] as number;
                    return (
                      <td
                        key={k}
                        className={`px-3 py-2.5 text-center tabular-nums text-xs font-medium ${probBg(p)}`}
                      >
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

export default function SimulatePage() {
  const [mode, setMode] = useState<"live" | "custom">("live");
  const [groups, setGroups] = useState<Groups>(WC2026_GROUPS);
  const [nSims, setNSims] = useState(10_000);
  const [seed, setSeed] = useState(42);
  const [result, setResult] = useState<SimulateResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function updateElo(group: string, idx: number, elo: number) {
    setGroups((prev) => ({
      ...prev,
      [group]: prev[group].map((t, i) => (i === idx ? { ...t, elo } : t)),
    }));
  }

  async function runSim() {
    setLoading(true);
    setError("");
    try {
      const res =
        mode === "live"
          ? await simulateWC2026(nSims, seed)
          : await simulate({ groups, n_sims: nSims, seed });
      setResult(res);
    } catch {
      setError("Simulation failed — is the API running at localhost:8000?");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="container mx-auto px-4 py-10 max-w-7xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Monte Carlo Simulator</h1>
        <p className="text-white/40 mt-1 text-sm">WC 2026 — Poisson goal model on Elo + OOP ratings</p>
      </div>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-8 p-1 bg-white/5 border border-white/8 rounded-xl w-fit">
        {(["live", "custom"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`px-5 py-2 rounded-lg text-sm font-medium transition-colors ${
              mode === m ? "bg-white text-black" : "text-white/50 hover:text-white"
            }`}
          >
            {m === "live" ? "Live (DB Elo + OOP)" : "Custom Groups"}
          </button>
        ))}
      </div>

      {/* Custom groups editor */}
      {mode === "custom" && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-4 mb-8">
          {Object.entries(groups).map(([letter, teams]) => (
            <div key={letter} className="bg-white/5 border border-white/8 rounded-xl p-4">
              <p className="text-white/50 text-xs font-semibold uppercase tracking-wider mb-3">
                Group {letter}
              </p>
              <div className="space-y-2">
                {teams.map((team, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-lg leading-none">{getFlag(team.name)}</span>
                    <span className="text-white/70 text-xs flex-1 truncate">{team.name}</span>
                    <input
                      type="number"
                      value={team.elo}
                      onChange={(e) => updateElo(letter, i, Number(e.target.value))}
                      className="w-16 bg-white/5 border border-white/10 rounded px-1.5 py-1 text-xs text-right text-emerald-400 tabular-nums focus:outline-none focus:border-white/25"
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {mode === "live" && (
        <div className="mb-8 bg-white/5 border border-white/8 rounded-xl p-5 text-white/50 text-sm">
          Pulls current Elo ratings and OOP composites directly from the database.
          Groups follow the actual WC 2026 draw.
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-6 mb-8 bg-white/5 border border-white/8 rounded-xl p-5">
        <div className="flex-1 min-w-48">
          <label className="text-white/50 text-xs font-medium block mb-2">
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
          <label className="text-white/50 text-xs font-medium block mb-2">Random Seed</label>
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
          className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold transition-colors"
        >
          {loading ? "Running…" : "Run Simulation"}
        </button>
      </div>

      {error && <p className="text-red-400 text-sm mb-6">{error}</p>}

      {result && <ResultsTable result={result} />}
    </main>
  );
}
