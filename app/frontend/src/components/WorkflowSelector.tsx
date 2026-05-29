"use client";

import { VT323 } from "next/font/google";
import type { Workflow } from "@/lib/types";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface Option {
  value: Workflow;
  name: string;
  tag: string;
  desc: string;
  highlight?: boolean;
}

const OPTIONS: Option[] = [
  {
    value: "cognitive",
    name: "Cognitive",
    tag: "Reasoning-Gen",
    desc: "Swarm 5 agents → Debate → CIO.",
    highlight: true,
  },
  {
    value: "traditional",
    name: "Traditional",
    tag: "Score-Driven",
    desc: "Alpha + RSI + P/E, cân tỷ trọng cố định.",
  },
  {
    value: "kelly",
    name: "Kelly",
    tag: "Wealth-Max",
    desc: "Tối ưu kích thước vị thế theo payoff.",
  },
  {
    value: "markowitz",
    name: "Markowitz",
    tag: "Risk-Balancing",
    desc: "Mean-Variance, đa dạng hoá.",
  },
];

interface Props {
  value: Workflow;
  onChange: (w: Workflow) => void;
}

export function WorkflowSelector({ value, onChange }: Props) {
  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="tagline">Bước 02</span>
          <h3
            className={`${vt323.className} text-xl uppercase tracking-[0.06em] text-black leading-none`}
          >
            Workflow
          </h3>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        {OPTIONS.map((opt) => {
          const on = value === opt.value;
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              className={`text-left px-3 py-2.5 border-2 border-black transition-all relative ${
                on
                  ? "bg-[#FAAD14] shadow-[2px_2px_0_#000000]"
                  : "bg-white hover:bg-[#FFF6E0] shadow-[1px_1px_0_#000000]"
              }`}
            >
              <div className="flex items-center gap-2">
                <span
                  className={`w-3 h-3 rounded-full border-2 border-black flex-shrink-0 ${
                    on ? "bg-black" : "bg-white"
                  }`}
                />
                <span
                  className={`${vt323.className} text-lg uppercase tracking-wider leading-none text-black`}
                >
                  {opt.name}
                </span>
                {opt.highlight && !on && (
                  <span className="ml-auto text-[8px] font-mono uppercase tracking-widest font-bold text-[#B33A00]">
                    ★
                  </span>
                )}
              </div>
              <div className="mt-1 ml-5 text-[9px] uppercase tracking-[0.16em] font-mono font-bold text-[#555555]">
                {opt.tag}
              </div>
              <p
                className={`mt-0.5 ml-5 text-[10px] leading-snug ${
                  on ? "text-black/80" : "text-[#555555]"
                }`}
              >
                {opt.desc}
              </p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
