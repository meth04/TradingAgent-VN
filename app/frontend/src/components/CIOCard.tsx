"use client";

import { VT323 } from "next/font/google";
import type { CIOResult } from "@/lib/types";
import { StatBlock } from "./StatBlock";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface Props {
  result?: CIOResult;
  ticker: string;
}

export function CIOCard({ result, ticker }: Props) {
  if (!result) {
    return (
      <article className="surface border-l-[8px] border-l-[#D0D0D0] p-6 opacity-90">
        <header className="flex items-center justify-between mb-3">
          <div>
            <div className="tagline">Chief Investment Officer</div>
            <h3
              className={`${vt323.className} text-2xl uppercase tracking-wider text-black mt-1`}
            >
              Quyết định CIO · {ticker}
            </h3>
          </div>
          <span className="badge badge-info">
            <span className="dot" /> Chờ 5 agents
          </span>
        </header>
        <div className="text-[#555555] text-sm font-mono">
          CIO đang chờ kết quả từ swarm để tổng hợp và ra IntentTicket cuối cùng…
        </div>
      </article>
    );
  }

  const conf = result.confidence > 1 ? result.confidence : result.confidence * 100;
  const confPct = Math.max(0, Math.min(100, Math.round(conf)));

  const isBuy = result.action.startsWith("BUY");
  const isSell = result.action === "SELL" || result.action === "TRIMMING";

  const stripColor = isBuy
    ? "border-l-[#10A37F]"
    : isSell
      ? "border-l-[#EF4444]"
      : "border-l-[#D0D0D0]";

  const actionBg = isBuy
    ? "bg-[#10A37F]"
    : isSell
      ? "bg-[#EF4444]"
      : "bg-[#888888]";

  const conviction =
    confPct >= 75 ? "HIGH" : confPct >= 55 ? "MEDIUM" : confPct >= 35 ? "LOW" : "VERY LOW";

  return (
    <article className={`surface border-l-[8px] ${stripColor} p-6 flex flex-col`}>
      <header className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <div className="tagline">Chief Investment Officer</div>
          <h3
            className={`${vt323.className} text-2xl uppercase tracking-wider text-black leading-none mt-1`}
          >
            Quyết định CIO · {ticker}
          </h3>
        </div>
        <span
          className={`${actionBg} text-white px-4 py-2 font-mono font-bold tracking-[0.18em] text-sm uppercase border-2 border-black shadow-[3px_3px_0_#000000]`}
        >
          {result.action}
        </span>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-5">
        <StatBlock
          label="Weight target"
          value={`${result.weight_pct.toFixed(1)}%`}
          tone={result.weight_pct > 0 ? "gold" : "default"}
        />
        <StatBlock
          label="Confidence"
          value={`${confPct}%`}
          sub={
            <div className="h-[6px] bg-[var(--bg-warm)] mt-1 w-full border border-black">
              <div
                className="h-full bg-[#FAAD14] transition-all"
                style={{ width: `${confPct}%` }}
              />
            </div>
          }
        />
        <StatBlock
          label="Conviction"
          value={conviction}
          tone={
            conviction === "HIGH"
              ? "green"
              : conviction === "MEDIUM"
                ? "gold"
                : "coral"
          }
          className="col-span-2 md:col-span-1"
        />
      </div>

      <div className="border-l-4 border-[#FAAD14] pl-4 mb-4 bg-[var(--bg-warm)] py-2">
        <div className="tagline mb-1">Reasoning</div>
        <p className="text-[13px] leading-relaxed text-[#333333] whitespace-pre-wrap">
          {result.reasoning}
        </p>
      </div>

      {result.debate_summary && (
        <details className="mt-1 border-t-2 border-[#E8E2D6] pt-3">
          <summary className="cursor-pointer tagline hover:text-[#FAAD14]">
            Bull / Bear debate summary
          </summary>
          <p className="mt-2 text-xs text-[#555555] whitespace-pre-wrap leading-relaxed">
            {result.debate_summary}
          </p>
        </details>
      )}
    </article>
  );
}
