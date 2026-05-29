"use client";

import { VT323 } from "next/font/google";
import { ReactNode } from "react";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface Props {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "gold" | "green" | "red" | "coral" | "lilac";
  className?: string;
}

const TONE: Record<NonNullable<Props["tone"]>, string> = {
  default: "text-black",
  gold: "text-[#8B5A00]",
  green: "text-[#0B6E54]",
  red: "text-[#B91C1C]",
  coral: "text-[#B33A00]",
  lilac: "text-[#5B36B5]",
};

export function StatBlock({ label, value, sub, tone = "default", className = "" }: Props) {
  return (
    <div className={`stat-block ${className}`}>
      <div className="label">{label}</div>
      <div
        className={`${vt323.className} text-[28px] leading-none tracking-wider ${TONE[tone]}`}
      >
        {value}
      </div>
      {sub && (
        <div className="mt-1.5 text-[11px] font-mono text-[#555555] leading-none">
          {sub}
        </div>
      )}
    </div>
  );
}
