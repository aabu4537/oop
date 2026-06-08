"use client";

import { useEffect, useState } from "react";
import { getTeams, type Team } from "@/lib/api";
import { getFlag } from "@/lib/flags";

const ELO_MIN = 1400;
const ELO_MAX = 2200;

function eloPercent(elo: number) {
  return Math.max(0, Math.min(100, ((elo - ELO_MIN) / (ELO_MAX - ELO_MIN)) * 100));
}

function eloColor(elo: number) {
  if (elo >= 2000) return "from-emerald-500 to-emerald-400";
  if (elo >= 1800) return "from-blue-500 to-blue-400";
  if (elo >= 1600) return "from-amber-500 to-amber-400";
  return "from-red-600 to-red-500";
}

export default function TeamsPage() {
  const [teams, setTeams] = useState<Team[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    getTeams()
      .then((data) => {
        setTeams(data);
        if (data.length === 0) setError(true);
      })
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="container mx-auto px-4 py-10 max-w-6xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Teams</h1>
        <p className="text-white/40 mt-1 text-sm">Ranked by Elo rating</p>
      </div>

      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {Array.from({ length: 12 }).map((_, i) => (
            <div key={i} className="bg-white/5 rounded-xl p-4 animate-pulse h-24" />
          ))}
        </div>
      )}

      {error && !loading && (
        <div className="text-center py-20 text-white/40">
          <p className="text-4xl mb-3">🏳️</p>
          <p>No teams found. Run the ETL pipeline first.</p>
          <code className="mt-3 block text-xs text-white/25">python3.11 -m src.etl.ingest_elo</code>
        </div>
      )}

      {!loading && !error && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {teams.map((team, i) => (
            <div
              key={team.team_id}
              className="group bg-white/5 border border-white/8 rounded-xl p-4 hover:bg-white/8 hover:border-white/15 transition-all duration-200"
            >
              <div className="flex items-center gap-3 mb-3">
                <span className="text-3xl leading-none">{getFlag(team.name)}</span>
                <div className="flex-1 min-w-0">
                  <p className="font-semibold text-white text-sm truncate">{team.name}</p>
                  <p className="text-white/35 text-xs">{team.fifa_code ?? "—"}</p>
                </div>
                <span className="text-white/25 text-xs font-mono shrink-0">#{i + 1}</span>
              </div>

              {team.elo_rating != null ? (
                <div>
                  <div className="flex justify-between text-xs mb-1.5">
                    <span className="text-white/40">Elo</span>
                    <span className="text-emerald-400 font-semibold tabular-nums">
                      {team.elo_rating.toFixed(0)}
                    </span>
                  </div>
                  <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                    <div
                      className={`h-full bg-gradient-to-r ${eloColor(team.elo_rating)} rounded-full transition-all duration-500`}
                      style={{ width: `${eloPercent(team.elo_rating)}%` }}
                    />
                  </div>
                </div>
              ) : (
                <div className="text-white/25 text-xs">No Elo data</div>
              )}
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
