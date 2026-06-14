import Link from "next/link";
import { HeroGeometric } from "@/components/ui/shape-landing-hero";

export default function Home() {
  return (
    <div className="relative">
      <HeroGeometric
        badge="Raumdeuter · WC 2026"
        title1="Predict the"
        title2="Beautiful Game"
      />

      {/* CTA overlaid at bottom of hero */}
      <div className="absolute bottom-16 left-0 right-0 z-20 flex justify-center gap-4">
        <Link
          href="/simulate"
          className="px-7 py-3 rounded-xl bg-white text-black text-sm font-semibold hover:bg-white/90 transition-colors"
        >
          Run Simulation →
        </Link>
        <Link
          href="/teams"
          className="px-7 py-3 rounded-xl bg-white/10 border border-white/15 text-white text-sm font-semibold hover:bg-white/15 transition-colors backdrop-blur-md"
        >
          Elo Rankings
        </Link>
      </div>
    </div>
  );
}
