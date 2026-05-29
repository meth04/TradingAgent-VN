"use client";

import { VT323 } from "next/font/google";
import { ReactNode } from "react";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface Props {
  step?: string;
  title: string;
  trailing?: ReactNode;
}

export function SectionHeader({ step, title, trailing }: Props) {
  return (
    <div className="flex items-end gap-4 mb-5">
      {step && (
        <span className="tagline pb-1">{step}</span>
      )}
      <h2
        className={`${vt323.className} text-3xl md:text-4xl uppercase tracking-[0.06em] text-black leading-none`}
      >
        {title}
      </h2>
      <div className="section-rule mb-2" />
      {trailing}
    </div>
  );
}
