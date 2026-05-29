"use client";

import { VT323 } from "next/font/google";
import { ReactNode } from "react";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface SideStat {
  label: string;
  value: string;
  accent?: "gold" | "green" | "coral" | "red" | "lilac";
}

interface Props {
  tagline: string;
  title: string;
  subtitle?: string;
  rightChips?: SideStat[];
  children?: ReactNode;
}

const ACCENT: Record<NonNullable<SideStat["accent"]>, string> = {
  gold: "border-[#FAAD14] text-[#8B5A00] bg-[#FFF6E0]",
  green: "border-[#10A37F] text-[#0B6E54] bg-[#E8F5EE]",
  coral: "border-[#FF6B35] text-[#B33A00] bg-[#FFE9DC]",
  red: "border-[#EF4444] text-[#B91C1C] bg-[#FBE9E9]",
  lilac: "border-[#8B5CF6] text-[#5B36B5] bg-[#F1EBFA]",
};

export function HeroBlock({ tagline, title, subtitle, rightChips, children }: Props) {
  return (
    <section className="mb-8">
      <div className="tagline mb-2">{tagline}</div>
      <h1
        className={`${vt323.className} text-4xl md:text-6xl uppercase leading-none tracking-[0.04em] text-black mb-3`}
      >
        {title}
      </h1>
      {subtitle && (
        <p className="max-w-3xl text-[13px] leading-7 text-[#555555]">
          {subtitle}
        </p>
      )}
      {children}

      {rightChips && rightChips.length > 0 && (
        <div className="mt-5 flex flex-wrap gap-2">
          {rightChips.map((c, i) => {
            const accent = ACCENT[c.accent ?? "gold"];
            return (
              <div
                key={i}
                className={`border-2 ${accent} px-3 py-1.5 flex items-baseline gap-2`}
              >
                <span className="text-[9px] uppercase tracking-[0.22em] font-mono font-bold opacity-70">
                  {c.label}
                </span>
                <span
                  className={`${vt323.className} text-base leading-none tracking-wider`}
                >
                  {c.value}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
