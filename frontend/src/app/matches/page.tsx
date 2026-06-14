"use client";

import { useEffect, useState } from "react";
import { getMatches, type Match } from "@/lib/api";
import { getFlag } from "@/lib/flags";

export default function MatchesPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [competition, setCompetition] = useState("FIFA World Cup");
  const [season, setSeason] = useState("");

  function load(comp: string, sea: string) {
    setLoading(true);
    getMatches({ competition: comp || undefined, season: sea || undefined, limit: 100 })
      .then(setMatches)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load("FIFA World Cup", "");
  }, []);

  return (
    <main className="container mx-auto px-4 py-10 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Matches</h1>
        <p className="text-white/40 mt-1 text-sm">Filter by competition or season</p>
      </div>

      <div className="flex gap-3 mb-8 flex-wrap">
        <input
          value={competition}
          onChange={(e) => setCompetition(e.target.value)}
          placeholder="Competition (e.g. FIFA World Cup)"
          className="flex-1 min-w-48 bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/25"
        />
        <input
          value={season}
          onChange={(e) => setSeason(e.target.value)}
          placeholder="Season (e.g. 2022)"
          className="w-40 bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/25"
        />
        <button
          onClick={() => load(competition, season)}
          className="px-5 py-2.5 bg-white text-black rounded-lg text-sm font-semibold hover:bg-white/90 transition-colors"
        >
          Search
        </button>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bg-white/5 rounded-xl h-16 animate-pulse" />
          ))}
        </div>
      ) : matches.length === 0 ? (
        <div className="text-center py-20 text-white/40">
          <p className="text-4xl mb-3">📅</p>
          <p>No matches found. Try different filters.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {matches.map((m) => {
            const home = m.home_team_name ?? m.home_team_id?.slice(0, 8) ?? "?";
            const away = m.away_team_name ?? m.away_team_id?.slice(0, 8) ?? "?";
            const score =
              m.home_score != null && m.away_score != null
                ? `${m.home_score} – ${m.away_score}`
                : "vs";
            return (
              <div
                key={m.match_id}
                className="bg-white/5 border border-white/8 rounded-xl px-5 py-3 flex items-center gap-4 hover:bg-white/8 transition-colors"
              >
                <span className="text-white/30 text-xs tabular-nums w-20 shrink-0">
                  {m.match_date}
                </span>
                <div className="flex-1 grid grid-cols-3 items-center gap-2 text-sm">
                  <div className="flex items-center gap-2 justify-end">
                    <span className="text-white/70 truncate">{home}</span>
                    <span className="text-lg leading-none shrink-0">{getFlag(home)}</span>
                  </div>
                  <p className="text-center font-bold text-white tabular-nums">{score}</p>
                  <div className="flex items-center gap-2 justify-start">
                    <span className="text-lg leading-none shrink-0">{getFlag(away)}</span>
                    <span className="text-white/70 truncate">{away}</span>
                  </div>
                </div>
                <div className="text-right shrink-0 hidden sm:block">
                  <p className="text-white/40 text-xs">{m.competition}</p>
                  <p className="text-white/25 text-xs">{m.season}</p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </main>
  );
}
