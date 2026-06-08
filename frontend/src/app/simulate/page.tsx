"use client";

import { useState } from "react";
import { simulate, type SimulateResponse } from "@/lib/api";
import { getFlag } from "@/lib/flags";

type TeamEntry = { name: string; elo: number };
type Groups = Record<string, TeamEntry[]>;

const DEFAULT_GROUPS: Groups = {
  A: [{ name: "Qatar", elo: 1550 }, { name: "Ecuador", elo: 1769 }, { name: "Senegal", elo: 1746 }, { name: "Netherlands", elo: 1990 }],
  B: [{ name: "England", elo: 1950 }, { name: "Iran", elo: 1706 }, { name: "USA", elo: 1827 }, { name: "Wales", elo: 1800 }],
  C: [{ name: "Argentina", elo: 2142 }, { name: "Saudi Arabia", elo: 1634 }, { name: "Mexico", elo: 1848 }, { name: "Poland", elo: 1826 }],
  D: [{ name: "France", elo: 2003 }, { name: "Australia", elo: 1726 }, { name: "Denmark", elo: 1843 }, { name: "Tunisia", elo: 1705 }],
  E: [{ name: "Spain", elo: 1975 }, { name: "Costa Rica", elo: 1650 }, { name: "Germany", elo: 1988 }, { name: "Japan", elo: 1725 }],
  F: [{ name: "Belgium", elo: 1928 }, { name: "Canada", elo: 1735 }, { name: "Morocco", elo: 1779 }, { name: "Croatia", elo: 1944 }],
  G: [{ name: "Brazil", elo: 2045 }, { name: "Serbia", elo: 1800 }, { name: "Switzerland", elo: 1879 }, { name: "Cameroon", elo: 1603 }],
  H: [{ name: "Portugal", elo: 1960 }, { name: "Ghana", elo: 1607 }, { name: "Uruguay", elo: 1890 }, { name: "South Korea", elo: 1732 }],
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

export default function SimulatePage() {
  const [groups, setGroups] = useState<Groups>(DEFAULT_GROUPS);
  const [nSims, setNSims] = useState(5000);
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
      const res = await simulate({ groups, n_sims: nSims, seed });
      setResult(res);
    } catch (e) {
      setError("Simulation failed — is the API running at localhost:8000?");
    } finally {
      setLoading(false);
    }
  }

  const stageKeys = result
    ? (Object.keys(result.results[0]).filter((k) => k !== "team") as string[])
    : [];

  return (
    <main className="container mx-auto px-4 py-10 max-w-7xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Monte Carlo Simulator</h1>
        <p className="text-white/40 mt-1 text-sm">Edit Elo ratings, set simulations, hit Run</p>
      </div>

      {/* Groups editor */}
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

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-6 mb-8 bg-white/5 border border-white/8 rounded-xl p-5">
        <div className="flex-1 min-w-48">
          <label className="text-white/50 text-xs font-medium block mb-2">
            Simulations: <span className="text-white">{nSims.toLocaleString()}</span>
          </label>
          <input
            type="range"
            min={100}
            max={10000}
            step={100}
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

      {/* Results */}
      {result && (
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
                {result.results.map((row) => {
                  const name = row.team as string;
                  return (
                    <tr key={name} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                      <td className="px-4 py-2.5 flex items-center gap-2">
                        <span className="text-lg leading-none">{getFlag(name)}</span>
                        <span className="text-white/80 text-sm">{name}</span>
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
      )}
    </main>
  );
}
