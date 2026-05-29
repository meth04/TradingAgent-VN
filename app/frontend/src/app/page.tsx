"use client";

import { useEffect, useState } from "react";
import { VT323 } from "next/font/google";
import { TickerSelector } from "@/components/TickerSelector";
import { WorkflowSelector } from "@/components/WorkflowSelector";
import { AnalysisPanel } from "@/components/AnalysisPanel";
import { HeroBlock } from "@/components/HeroBlock";
import { Sidebar, SidebarDivider } from "@/components/Sidebar";
import type { Workflow } from "@/lib/types";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export const TICKERS = ["FPT", "HPG", "VCB", "SSI", "GAS"];

export default function HomePage() {
  const [selected, setSelected] = useState<string[]>(["FPT"]);
  const [workflow, setWorkflow] = useState<Workflow>("cognitive");
  const [running, setRunning] = useState(false);
  const [runKey, setRunKey] = useState(0);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  function startRun() {
    if (selected.length === 0 || running) return;
    setRunning(true);
    setRunKey((k) => k + 1);
  }

  const heroChips = [
    { label: "Phiên", value: now.toLocaleDateString("vi-VN"), accent: "gold" as const },
    { label: "Engine", value: "gpt-5.2", accent: "coral" as const },
    { label: "Agents", value: "5/5", accent: "green" as const },
  ];

  return (
    <div className="w-full px-4 py-8 md:px-8 md:py-10">
      <div className="mx-auto w-full max-w-[1500px] grid lg:grid-cols-[320px_minmax(0,1fr)] gap-6">
        {/* SIDEBAR */}
        <Sidebar
          footer={
            <div className="flex flex-col gap-2">
              <div className="text-[10px] font-mono uppercase tracking-[0.18em] text-[#555555]">
                Tóm tắt
              </div>
              <div className="text-[11px] font-mono text-[#333333] leading-relaxed">
                <div>
                  Mã:{" "}
                  <span className="font-bold text-black">
                    {selected.length === 0 ? "—" : selected.join(", ")}
                  </span>
                </div>
                <div>
                  Workflow:{" "}
                  <span className="font-bold text-black uppercase">{workflow}</span>
                </div>
              </div>
              <button
                onClick={startRun}
                disabled={selected.length === 0 || running}
                className="btn-primary w-full text-center mt-1"
              >
                {running ? "Đang chạy..." : "Phân tích"}
              </button>
              <div className="flex items-center gap-2 text-[10px] font-mono text-[#555555] uppercase tracking-[0.18em] mt-1">
                <span className="dot" />
                <span>5/5 agents online</span>
              </div>
            </div>
          }
        >
          <TickerSelector
            tickers={TICKERS}
            selected={selected}
            onChange={setSelected}
          />
          <SidebarDivider />
          <WorkflowSelector value={workflow} onChange={setWorkflow} />
        </Sidebar>

        {/* CANVAS */}
        <div className="min-w-0">
          <HeroBlock
            tagline="Multi-Agent · VN30"
            title="Stock Analyzer"
            subtitle="5 agent chuyên gia (Macro · Technical · Quant · News · Financial) chạy song song trên VN30, dung hoà bằng CIO và xuất báo cáo Markdown. Mỗi agent hoàn thành sẽ hiện ngay trên panel."
            rightChips={heroChips}
          />

          {runKey === 0 ? (
            <div className="pixel-border surface-warm p-10 text-center">
              <div
                className={`${vt323.className} text-3xl uppercase tracking-[0.08em] text-black mb-3`}
              >
                Sẵn sàng phân tích
              </div>
              <p className="text-sm text-[#555555] max-w-md mx-auto leading-relaxed">
                Chọn mã cổ phiếu và workflow ở thanh bên trái, sau đó bấm{" "}
                <span className="font-bold text-black">Phân tích</span>. Mỗi agent
                xong sẽ tự đẩy lên panel — không cần F5.
              </p>
            </div>
          ) : (
            <AnalysisPanel
              key={runKey}
              tickers={selected}
              workflow={workflow}
              onFinish={() => setRunning(false)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
