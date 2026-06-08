import type { Metadata } from "next";
import "./globals.css";
import { Nav } from "@/components/nav";

export const metadata: Metadata = {
  title: "Raumdeuter",
  description: "World Cup prediction and simulation platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark h-full">
      <body className="min-h-full bg-neutral-950 text-white antialiased">
        <Nav />
        {children}
      </body>
    </html>
  );
}
