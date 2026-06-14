"use client";

import { useEffect, useState, useMemo } from "react";
import { getMatches, type Match } from "@/lib/api";
import { getFlag } from "@/lib/flags";

const CODE_TO_NAME: Record<string, string> = {
  ESP: "Spain", ENG: "England", FRA: "France", GER: "Germany",
  BRA: "Brazil", ARG: "Argentina", POR: "Portugal", NED: "Netherlands",
  BEL: "Belgium", URU: "Uruguay", SEN: "Senegal", MAR: "Morocco",
  JPN: "Japan", KOR: "South Korea", MEX: "Mexico", USA: "United States",
  CAN: "Canada", AUS: "Australia", CRO: "Croatia", SUI: "Switzerland",
  DEN: "Denmark", SRB: "Serbia", COL: "Colombia", ECU: "Ecuador",
  IRN: "Iran", TUN: "Tunisia", EGY: "Egypt", NGA: "Nigeria",
  CMR: "Cameroon", GHA: "Ghana", SAU: "Saudi Arabia", QAT: "Qatar",
};

function resolveName(raw: string | null | undefined): string {
  if (!raw) return "?";
  return CODE_TO_NAME[raw] ?? raw;
}

export default function MatchesPage() {
  const [matches, setMatches] = useState<Match[]>([]);
  const [loading, setLoading] = useState(true);
  const [competition, setCompetition] = useState("FIFA World Cup");
  const [textFilter, setTextFilter] = useState("");

  function load(comp: string) {
    setLoading(true);
    getMatches({ competition: comp || undefined, limit: 500 })
      .then(setMatches)
      .finally(() => setLoading(false));
  }

  useEffect(() => { load("FIFA World Cup"); }, []);

  const visible = useMemo(() => {
    const q = textFilter.trim().toLowerCase();
    if (!q) return matches;
    return matches.filter((m) => {
      const home = resolveName(m.home_team_name).toLowerCase();
      const away = resolveName(m.away_team_name).toLowerCase();
      const date = (m.match_date ?? "").toLowerCase();
      const comp = (m.competition ?? "").toLowerCase();
      return home.includes(q) || away.includes(q) || date.includes(q) || comp.includes(q);
    });
  }, [matches, textFilter]);

  return (
    <main className="container mx-auto px-4 py-10 max-w-5xl">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white">Matches</h1>
        <p className="text-white/40 mt-1 text-sm">Search by team, date, or competition</p>
      </div>

      <div className="flex gap-3 mb-4 flex-wrap">
        <input
          value={competition}
          onChange={(e) => setCompetition(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(competition)}
          placeholder="Competition (e.g. FIFA World Cup)"
          className="flex-1 min-w-48 bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/25"
        />
        <button
          onClick={() => load(competition)}
          className="px-5 py-2.5 bg-white text-black rounded-lg text-sm font-semibold hover:bg-white/90 transition-colors"
        >
          Load
        </button>
      </div>

      <div className="mb-8">
        <input
          value={textFilter}
          onChange={(e) => setTextFilter(e.target.value)}
          placeholder="Filter by team, date (e.g. 2026), or competition…"
          className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-2.5 text-sm text-white placeholder:text-white/30 focus:outline-none focus:border-white/25"
        />
        {textFilter && (
          <p className="text-white/30 text-xs mt-1.5 pl-1">
            {visible.length} of {matches.length} matches
          </p>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="bg-white/5 rounded-xl h-16 animate-pulse" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="text-center py-20 text-white/40">
          <p className="text-4xl mb-3">📅</p>
          <p>{matches.length === 0 ? "No matches found. Try a different competition." : "No matches match your filter."}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map((m) => {
            const home = resolveName(m.home_team_name);
            const away = resolveName(m.away_team_name);
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
