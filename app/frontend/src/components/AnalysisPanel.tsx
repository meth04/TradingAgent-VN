"use client";

import { useEffect, useRef, useState } from "react";
import { VT323 } from "next/font/google";
import { createAnalysis, getAnalysisJob } from "@/lib/api";
import type { AgentResult, JobSnapshot, Workflow } from "@/lib/types";
import { AnalysisCard } from "./AnalysisCard";
import { CIOCard } from "./CIOCard";
import { ReportCard } from "./ReportCard";
import { SectionHeader } from "./SectionHeader";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const AGENTS = ["macro", "technical", "quant", "news", "financial"] as const;

const POLL_INTERVAL_MS = 1000;

interface Props {
  tickers: string[];
  workflow: Workflow;
  onFinish: () => void;
}

const PHASE_LABEL: Record<string, string> = {
  init: "Đang khởi tạo",
  crawl: "Sync giá & crawl tin",
  agents: "5 agents đang chạy",
  cio: "CIO đang tổng hợp",
  report: "Đang sinh báo cáo",
  done: "Hoàn tất",
};

export function AnalysisPanel({ tickers, workflow, onFinish }: Props) {
  const [snap, setSnap] = useState<JobSnapshot | null>(null);
  const [error, setError] = useState<string>("");
  const [elapsed, setElapsed] = useState(0);
  const [startedAt] = useState(() => Date.now());
  const onFinishRef = useRef(onFinish);
  onFinishRef.current = onFinish;

  const isDone = snap?.status === "done" || snap?.status === "error";

  // Stopwatch — purely client-side so it ticks even between polls.
  useEffect(() => {
    if (isDone) return;
    const id = setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [isDone, startedAt]);

  // Create the job, then poll its snapshot every POLL_INTERVAL_MS.
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | null = null;
    let alive = true;
    let jobId: string | null = null;

    async function start() {
      try {
        const { job_id } = await createAnalysis(tickers, workflow, abort.signal);
        if (!alive) return;
        jobId = job_id;
        await poll();
      } catch (e: unknown) {
        if (!alive) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const msg = e instanceof Error ? e.message : String(e);
        if (/aborted/i.test(msg)) return;
        setError(msg);
        onFinishRef.current();
      }
    }

    async function poll() {
      if (!alive || !jobId) return;
      try {
        const s = await getAnalysisJob(jobId, abort.signal);
        if (!alive) return;
        setSnap(s);
        if (s.status === "done" || s.status === "error") {
          if (s.error) setError(s.error);
          onFinishRef.current();
          return;
        }
      } catch (e: unknown) {
        if (!alive) return;
        if (e instanceof DOMException && e.name === "AbortError") return;
        const msg = e instanceof Error ? e.message : String(e);
        if (/aborted/i.test(msg)) return;
        if (/HTTP 404/.test(msg)) {
          // Backend confirms job no longer exists (server restarted / evicted).
          // Stop polling — different from a transient 5xx or network blip.
          setError("Phiên phân tích đã hết hạn. Vui lòng bấm Phân tích lại.");
          onFinishRef.current();
          return;
        }
        console.warn("[poll] transient error", msg);
      }
      // Wrap poll() in a sync callback so its rejected Promise can't escape as
      // an unhandled rejection (React Strict Mode dev mode is noisy about this).
      timer = setTimeout(() => {
        poll().catch(() => {});
      }, POLL_INTERVAL_MS);
    }

    // Safety net: swallow any AbortError that surfaces outside the try/catch
    // when Strict Mode aborts the first effect's in-flight fetch.
    start().catch((e: unknown) => {
      if (e instanceof DOMException && e.name === "AbortError") return;
      const msg = e instanceof Error ? e.message : String(e);
      if (/aborted/i.test(msg)) return;
      console.warn("[start] uncaught", e);
    });

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      try {
        abort.abort();
      } catch {
        /* noop */
      }
    };
  }, [tickers, workflow]);

  const agentsByTicker = snap?.agents ?? {};
  const cioByTicker = snap?.cio ?? {};
  const totalAgents = tickers.length * AGENTS.length;
  let completedCount = 0;
  for (const t of tickers) {
    for (const a of agentsByTicker[t] || []) {
      if (a.status === "completed" || a.status === "error") completedCount++;
    }
  }
  const cioCount = Object.keys(cioByTicker).length;
  const progressPct = Math.min(100, Math.round((completedCount / totalAgents) * 100));
  const phaseLabel = snap?.phase ? PHASE_LABEL[snap.phase] || snap.phase : "Đang khởi tạo";

  return (
    <section className="space-y-12">
      {/* Progress strip */}
      <div className="surface surface-warm px-6 py-4 flex flex-wrap items-center gap-5">
        <div className="flex items-center gap-2">
          {snap?.status === "done" ? (
            <span className="badge badge-buy">Hoàn tất</span>
          ) : snap?.status === "error" ? (
            <span className="badge badge-sell">Lỗi</span>
          ) : (
            <span className="badge badge-info">
              <span className="dot" /> {phaseLabel}
            </span>
          )}
          <span className="tagline uppercase">{workflow}</span>
        </div>
        <div className="flex-1 min-w-[240px]">
          <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-widest text-[#555555] mb-1">
            <span>
              Agents {completedCount}/{totalAgents} · CIO {cioCount}/{tickers.length}
            </span>
            <span>{progressPct}%</span>
          </div>
          <div className="h-2 bg-white border-2 border-black">
            <div
              className="h-full bg-[#FAAD14] transition-all"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
        <div className={`${vt323.className} text-2xl text-black tracking-wider`}>
          {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, "0")}
        </div>
      </div>

      {error && (
        <div className="pixel-border bg-[#FBE9E9] border-[#EF4444] p-4 text-[#B91C1C] text-sm font-mono">
          {error}
        </div>
      )}

      {snap && snap.logs.length > 0 && (
        <details className="surface surface-soft p-3 text-[11px] font-mono text-[#555555]">
          <summary className="cursor-pointer tagline hover:text-[#FAAD14]">
            Logs ({snap.logs.length})
          </summary>
          <div className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[#333333]">
            {snap.logs.join("\n")}
          </div>
        </details>
      )}

      {tickers.map((ticker, idx) => {
        const agentList = agentsByTicker[ticker] || [];
        const byAgent: Record<string, AgentResult> = {};
        for (const a of agentList) byAgent[a.agent] = a;
        const cio = cioByTicker[ticker];
        const tickerProgress = agentList.filter(
          (a) => a.status === "completed" || a.status === "error",
        ).length;

        return (
          <div key={ticker} className="space-y-6">
            <SectionHeader
              step={`Mã ${String(idx + 1).padStart(2, "0")}`}
              title={ticker}
              trailing={
                <span className="text-[10px] font-mono uppercase tracking-widest text-[#555555] mb-2">
                  {tickerProgress}/{AGENTS.length} agents · CIO {cio ? "✓" : "..."}
                </span>
              }
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

      {(snap?.report || isDone) && (
        <>
          <SectionHeader step="Tổng hợp" title="Báo cáo" />
          <ReportCard content={snap?.report ?? ""} />
        </>
      )}
    </section>
  );
}
