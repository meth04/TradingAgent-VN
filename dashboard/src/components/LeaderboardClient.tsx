"use client";

import { useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import { VT323 } from "next/font/google";
import { usePlayback } from "@/contexts/PlaybackContext";
import { formatDate, formatPct, formatPctSigned, formatVND, formatVNDSign } from "@/lib/format";
import { computeLeaderboardForDate } from "@/lib/compute";
import type { LedgerEntry, PortfolioState } from "@/lib/data";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const WORKFLOW_DESCS = [
  {
    name: "Traditional",
    desc: "Baseline kế thừa, phù hợp để so sánh với các Workflow phức tạp hơn ở mức quyết định đơn mã.",
    surface: "bg-[#FFFFFF]",
  },
  {
    name: "Kelly",
    desc: "Baseline nhấn mạnh Position Sizing và kỷ luật phân bổ vốn theo xác suất và mức lợi thế ước lượng.",
    surface: "bg-[#F9F9F9]",
  },
  {
    name: "Markowitz",
    desc: "Baseline thiên về tối ưu hóa phân bổ danh mục ở cấp độ nhiều mã và rủi ro toàn rổ.",
    surface: "bg-[#F9F9F9]",
  },
  {
    name: "Cognitive",
    desc: "Workflow trung tâm của khóa luận, kết hợp phân tích đa tác tử, governance, CIO synthesis và risk gating.",
    surface: "bg-[#F5F5F5]",
  },
];

export function LeaderboardClient({
  states,
  ledgersAll,
  playbackDates,
}: {
  states: Record<string, PortfolioState>;
  ledgersAll: Record<string, Record<string, LedgerEntry[]>>;
  playbackDates: string[];
}) {
  const router = useRouter();
  const { dates, setDates, currentDate, setCurrentDate } = usePlayback();

  useEffect(() => {
    if (!dates.length && playbackDates.length) {
      setDates(playbackDates);
      if (!currentDate) setCurrentDate(playbackDates[playbackDates.length - 1]);
    }
  }, [dates.length, playbackDates, setDates, currentDate, setCurrentDate]);

  const { rows, displayDate } = useMemo(() => {
    if (!playbackDates.length) return { rows: [], displayDate: "" };
    const date = currentDate || playbackDates[playbackDates.length - 1];
    const cutoffIndex = playbackDates.indexOf(date);
    const ledgersForDate: Record<string, LedgerEntry[]> = {};
    Object.entries(ledgersAll).forEach(([ledgerDate, workflows]) => {
      if (ledgerDate <= date) {
        Object.entries(workflows).forEach(([wf, entries]) => {
          ledgersForDate[wf] = (ledgersForDate[wf] || []).concat(entries);
        });
      }
    });
    const computed = computeLeaderboardForDate(states, ledgersForDate, cutoffIndex);
    return { rows: computed, displayDate: date };
  }, [currentDate, playbackDates, states, ledgersAll]);

  if (!playbackDates.length) {
    return (
      <div className="w-full flex justify-center py-16">
        <div className="text-text-secondary">Không có dữ liệu khả dụng.</div>
      </div>
    );
  }

  return (
    <div className="w-full px-4 py-14 md:px-8 md:py-16">
      <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-14">
        <section className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">
              So sánh hiệu quả giữa các Workflow
            </div>
            <h1 className={`${vt323.className} text-6xl uppercase tracking-[0.08em] text-[#000000] md:text-7xl`}>
              Leaderboard
            </h1>
            <p className="max-w-3xl text-sm leading-8 text-[#666666] md:text-[15px]">
              Bảng này so sánh các Workflow dựa trên state và ledger đã được lưu ở cùng một mốc thời gian. Đây không phải bảng xếp hạng giao dịch trực tiếp. Mục tiêu chính là giúp người xem thấy được hiệu suất đầu tư của các workflow.
            </p>
          </div>
          <div className="pixel-border bg-[var(--surface-tint)] p-6 md:p-7">
            <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
              Mốc snapshot hiện tại
            </div>
            <div className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
              {formatDate(displayDate)}
            </div>
          </div>
        </section>

        <section className="pixel-border overflow-x-auto bg-[#FFFFFF]">
          <table className="min-w-full border-collapse">
            <thead>
              <tr className="bg-[#000000] text-[#FFFFFF] uppercase text-xs">
                {[
                  "Hạng",
                  "Workflow",
                  "Total Equity",
                  "Return",
                  "Total P&L",
                  "Win Rate",
                  "Biggest Win",
                  "Biggest Loss",
                  "Sharpe",
                  "Max Drawdown",
                  "Volatility",
                  "Profit Factor",
                  "Trades",
                ].map((col) => (
                  <th
                    key={col}
                    className={`${vt323.className} border border-[#000000] px-4 py-4 text-left text-sm tracking-[0.12em]`}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const isCognitive = row.workflow === "Cognitive";
                const rowClasses = isCognitive
                  ? "bg-[#F5F5F5]"
                  : i % 2 === 0
                    ? "bg-[#FFFFFF]"
                    : "bg-[#F9F9F9]";

                return (
                  <tr
                    key={row.workflow}
                    className={`${rowClasses} cursor-pointer border-b border-border-light transition-colors hover:bg-[#F5F5F5]`}
                    onClick={() => router.push(`/trading-view?workflow=${encodeURIComponent(row.workflow)}`)}
                  >
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm">{i + 1}</td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm font-bold uppercase text-[#000000]">
                      {row.workflow}
                    </td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm">{formatVND(row.totalEquity)}</td>
                    <td className={`border-r border-border-light px-4 py-4 font-mono text-sm font-bold ${row.returnPct >= 0 ? "text-[#10A37F]" : "text-[#EF4444]"}`}>
                      {formatPctSigned(row.returnPct)}
                    </td>
                    <td className={`border-r border-border-light px-4 py-4 font-mono text-sm ${row.pnl >= 0 ? "text-[#10A37F]" : "text-[#EF4444]"}`}>
                      {formatVNDSign(row.pnl)}
                    </td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm">{formatPct(row.winRate)}</td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm text-[#10A37F]">{formatVND(row.biggestWin)}</td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm text-[#EF4444]">{formatVND(row.biggestLoss)}</td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm">
                      {row.sharpe === 0 ? "—" : row.sharpe.toFixed(2)}
                    </td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm text-[#EF4444]">{row.mdd.toFixed(2)}%</td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm text-text-secondary">{row.volatility.toFixed(1)}%</td>
                    <td className="border-r border-border-light px-4 py-4 font-mono text-sm">
                      {row.profitFactor > 10 ? "9.9+" : row.profitFactor.toFixed(2)}
                    </td>
                    <td className="px-4 py-4 font-mono text-sm">{row.trades}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {WORKFLOW_DESCS.map((workflow) => (
            <article key={workflow.name} className={`pixel-border p-6 md:p-7 ${workflow.surface}`}>
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono"></div>
              <h2 className={`${vt323.className} mt-2 text-3xl uppercase tracking-[0.08em] text-[#000000]`}>
                {workflow.name}
              </h2>
              <p className="mt-4 text-sm leading-6 text-[#666666]">{workflow.desc}</p>
            </article>
          ))}
        </section>

        <div className="text-center text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">
          Các chỉ số được tính từ state, ledger và tiến trình backtest đã lưu trong repository.
        </div>
      </div>
    </div>
  );
}
