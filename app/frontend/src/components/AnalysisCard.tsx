"use client";

import { VT323 } from "next/font/google";
import type { AgentResult } from "@/lib/types";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const AGENT_META: Record<
  string,
  { label: string; stripe: string; tagline: string }
> = {
  macro: {
    label: "Macro",
    stripe: "border-l-[#FAAD14]",
    tagline: "Vĩ mô · Dòng tiền",
  },
  technical: {
    label: "Technical",
    stripe: "border-l-[#FF6B35]",
    tagline: "Đồ thị · Momentum",
  },
  quant: {
    label: "Quant",
    stripe: "border-l-[#8B5CF6]",
    tagline: "Alpha · Beta · Vol",
  },
  news: {
    label: "News",
    stripe: "border-l-[#10A37F]",
    tagline: "Sentiment · Sự kiện",
  },
  financial: {
    label: "Financial",
    stripe: "border-l-black",
    tagline: "BCTC · Định giá",
  },
};

interface Props {
  agent: string;
  ticker: string;
  state: AgentResult | "pending";
}

export function AnalysisCard({ agent, ticker, state }: Props) {
  const meta = AGENT_META[agent] ?? {
    label: agent,
    stripe: "border-l-[#D0D0D0]",
    tagline: "—",
  };
  const isSentinelPending = state === "pending";
  const status = isSentinelPending ? "pending" : state.status;
  const isLoading = status === "pending" || status === "running";
  const isError = status === "error";
  const data = isSentinelPending ? null : state;

  const statusBadge = isLoading ? (
    <span className="badge badge-info">
      <span className="dot" />{" "}
      {status === "running" ? "Đang chạy" : "Chờ tới lượt"}
    </span>
  ) : isError ? (
    <span className="badge badge-sell">Lỗi</span>
  ) : (
    <span className="badge badge-buy">Hoàn tất</span>
  );

  const actionBadge = data?.action ? (
    <span
      className={`badge ${
        data.action.startsWith("BUY")
          ? "badge-buy"
          : data.action === "SELL" || data.action === "TRIMMING"
            ? "badge-sell"
            : "badge-pass"
      }`}
    >
      {data.action}
    </span>
  ) : null;

  return (
    <article
      className={`surface border-l-[6px] ${meta.stripe} flex flex-col h-full`}
    >
      <header className="px-4 py-3 bg-[var(--bg-warm)] border-b-2 border-black">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div
              className={`${vt323.className} uppercase tracking-[0.12em] text-xl font-bold leading-none text-black`}
            >
              {meta.label}
            </div>
            <div className="text-[9px] uppercase tracking-[0.18em] text-[#555555] font-mono mt-1">
              {meta.tagline}
            </div>
          </div>
          <span className="text-[10px] font-mono text-[#555555] uppercase tracking-widest pt-1">
            {ticker}
          </span>
        </div>
      </header>

      <div className="px-4 py-2.5 flex flex-wrap items-center gap-1.5 border-b border-[#E8E2D6] bg-white">
        {statusBadge}
        {actionBadge}
        {typeof data?.confidence === "number" && (
          <span className="font-mono text-[10px] text-[#555555] ml-auto">
            conf {Math.round(data.confidence > 1 ? data.confidence : data.confidence * 100)}%
          </span>
        )}
      </div>

      <div className="px-4 py-3 flex-1 overflow-auto max-h-72 text-[12px] leading-relaxed font-mono text-[#333333] whitespace-pre-wrap bg-white">
        {isLoading ? (
          <div className="flex flex-col gap-1.5">
            <div className="h-2 bg-[var(--bg-warm)] w-3/4 animate-pulse" />
            <div className="h-2 bg-[var(--bg-warm)] w-1/2 animate-pulse" />
            <div className="h-2 bg-[var(--bg-warm)] w-2/3 animate-pulse" />
            <div className="text-[#888888] text-[11px] mt-2">
              {status === "running"
                ? "Agent đang gọi LLM..."
                : "Đang chờ slot rảnh..."}
            </div>
          </div>
        ) : isError ? (
          <span className="text-[#B91C1C]">{data?.error ?? data?.output}</span>
        ) : (
          (data?.output || "").trim() || (
            <span className="text-[#888888]">Không có dữ liệu</span>
          )
        )}
      </div>
    </article>
  );
}
