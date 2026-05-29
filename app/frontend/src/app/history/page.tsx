"use client";

import { useEffect, useState } from "react";
import { VT323 } from "next/font/google";
import { listHistory, getHistoryDetail } from "@/lib/api";
import type { HistoryListItem, HistoryDetail } from "@/lib/types";
import { AnalysisCard } from "@/components/AnalysisCard";
import { CIOCard } from "@/components/CIOCard";
import { ReportCard } from "@/components/ReportCard";
import { HeroBlock } from "@/components/HeroBlock";
import { SectionHeader } from "@/components/SectionHeader";
import { Sidebar } from "@/components/Sidebar";
import { formatTimestamp } from "@/lib/format";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const AGENTS = ["macro", "technical", "quant", "news", "financial"] as const;

const WORKFLOW_COLOR: Record<string, string> = {
  traditional: "border-l-black",
  kelly: "border-l-[#FAAD14]",
  markowitz: "border-l-[#8B5CF6]",
  cognitive: "border-l-[#FF6B35]",
};

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryListItem[]>([]);
  const [active, setActive] = useState<HistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  useEffect(() => {
    listHistory()
      .then(setItems)
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  async function open(id: string) {
    setErr("");
    try {
      const d = await getHistoryDetail(id);
      setActive(d);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  const heroChips = [
    {
      label: "Lượt chạy",
      value: String(items.length),
      accent: "gold" as const,
    },
    {
      label: "Mới nhất",
      value: items[0]?.timestamp
        ? new Date(items[0].timestamp).toLocaleDateString("vi-VN")
        : "—",
      accent: "coral" as const,
    },
  ];

  return (
    <div className="w-full px-4 py-8 md:px-8 md:py-10">
      <div className="mx-auto w-full max-w-[1500px] grid lg:grid-cols-[340px_minmax(0,1fr)] gap-6">
        {/* SIDEBAR: list of runs */}
        <Sidebar>
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="tagline">Archive</span>
                <h3
                  className={`${vt323.className} text-xl uppercase tracking-[0.06em] text-black leading-none`}
                >
                  Lịch sử
                </h3>
              </div>
              <span className="badge badge-info">{items.length}</span>
            </div>

            {loading ? (
              <div className="text-center text-[#888888] py-4 text-[11px] font-mono">
                Đang tải...
              </div>
            ) : items.length === 0 ? (
              <div className="text-center text-[#888888] py-6 text-[11px] italic">
                Chưa có phân tích nào.
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                {items.map((it) => {
                  const wf = (it.workflow || "").toLowerCase();
                  const stripe = WORKFLOW_COLOR[wf] || "border-l-black";
                  const isActive = active?.id === it.id;
                  return (
                    <button
                      key={it.id}
                      onClick={() => open(it.id)}
                      className={`text-left border-2 border-black border-l-[6px] ${stripe} p-2.5 transition-all ${
                        isActive
                          ? "bg-[#FAAD14] shadow-[2px_2px_0_#000000]"
                          : "bg-white hover:bg-[#FFF6E0] shadow-[1px_1px_0_#000000]"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex flex-wrap gap-0.5">
                          {it.tickers.map((t) => (
                            <span
                              key={t}
                              className="px-1.5 py-0 bg-white text-black font-mono text-[9px] uppercase tracking-widest font-bold border border-black"
                            >
                              {t}
                            </span>
                          ))}
                        </div>
                        <span
                          className={`${vt323.className} uppercase tracking-[0.08em] text-xs font-bold leading-none text-black`}
                        >
                          {it.workflow}
                        </span>
                      </div>
                      <div className="text-[9px] text-[#555555] font-mono tracking-wider">
                        {formatTimestamp(it.timestamp)}
                      </div>
                      <div className="text-[11px] text-[#333333] leading-snug line-clamp-2 mt-1">
                        {it.summary || "—"}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Sidebar>

        {/* CANVAS */}
        <div className="min-w-0">
          <HeroBlock
            tagline="Archive · app/data/history"
            title="Lịch sử phân tích"
            subtitle="Mọi lần chạy phân tích được lưu lại đầy đủ (5 agent outputs + CIO IntentTicket + Markdown report). Chọn một mục ở thanh bên trái để xem lại nguyên cảnh."
            rightChips={heroChips}
          />

          {err && (
            <div className="pixel-border bg-[#FBE9E9] border-[#EF4444] p-4 text-[#B91C1C] text-sm font-mono mb-6">
              {err}
            </div>
          )}

          {!active ? (
            <div className="pixel-border surface-warm p-10 text-center">
              <div
                className={`${vt323.className} text-3xl uppercase tracking-[0.08em] text-black mb-3`}
              >
                Chọn một phân tích
              </div>
              <p className="text-sm text-[#555555] max-w-md mx-auto leading-relaxed">
                Bấm vào một mục trong danh sách bên trái để xem chi tiết 5 agents,
                quyết định CIO và báo cáo Markdown đã lưu.
              </p>
            </div>
          ) : (
            <div className="space-y-10">
              <SectionHeader
                step="Chi tiết"
                title={active.id}
                trailing={
                  <button onClick={() => setActive(null)} className="btn-ghost mb-2">
                    × Đóng
                  </button>
                }
              />

              {active.tickers.map((ticker, idx) => {
                const agentList = active.agents[ticker] || [];
                const byAgent: Record<string, (typeof agentList)[number]> = {};
                for (const a of agentList) byAgent[a.agent] = a;
                const cio = active.cio[ticker];
                return (
                  <div key={ticker} className="space-y-6">
                    <SectionHeader
                      step={`Mã ${String(idx + 1).padStart(2, "0")}`}
                      title={ticker}
                    />
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
                      {AGENTS.map((a) => (
                        <AnalysisCard
                          key={a}
                          agent={a}
                          ticker={ticker}
                          state={byAgent[a] ?? "pending"}
                        />
                      ))}
                    </div>
                    <CIOCard ticker={ticker} result={cio} />
                  </div>
                );
              })}

              <SectionHeader step="Tổng hợp" title="Báo cáo" />
              <ReportCard content={active.report} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
