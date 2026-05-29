"use client";

import { useMemo } from "react";
import LightweightChart from "./LightweightChart";
import { LedgerEntry } from "../lib/data";

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Marker {
  time: string;
  position: "aboveBar" | "belowBar" | "inBar";
  color: string;
  text: string;
  id: string;
  investedAmount?: number;
  workflow?: string;
}

const WORKFLOW_MAP: Record<string, string> = {
  traditional: "0",
  kelly: "1",
  markowitz: "2",
  cognitive: "3",
};

function normalizeWorkflowName(entry: LedgerEntry): string {
  const wf = (entry.workflow || (entry as any).workflow_id || "").toString().trim().toLowerCase();
  if (wf.includes("traditional")) return "Traditional";
  if (wf.includes("kelly")) return "Kelly";
  if (wf.includes("markowitz")) return "Markowitz";
  if (wf.includes("cognitive")) return "Cognitive";
  return entry.workflow || "";
}

function normalizeWorkflowCode(entry: LedgerEntry): string {
  const wf = (entry.workflow || (entry as any).workflow_id || "").toString();
  const lower = wf.toLowerCase();
  const named = Object.keys(WORKFLOW_MAP).find((k) => lower.includes(k));
  if (named) return WORKFLOW_MAP[named];
  const tail = wf.split("-").pop() || wf;
  const digit = tail.match(/(0|1|2|3)/)?.[0];
  return digit ?? "0";
}

function getAvgBuyFromLedger(entries: LedgerEntry[], upToIndex: number, ticker: string, workflow: string): number | null {
  let totalInvest = 0;
  let totalQty = 0;

  for (let i = 0; i < upToIndex; i++) {
    const e = entries[i];
    if (e.ticker !== ticker) continue;
    const action = (e.action || "").toUpperCase();
    
    if (action === "BUY" || action === "BUY_MORE") {
      const qty = workflow === "Cognitive" ? (e.quantity || 0) : (e.quantity || 0) * 100;
      if (qty > 0) {
        totalInvest += qty * e.price;
        totalQty += qty;
      }
    } else if (action === "SELL" || action === "TRIMMING" || action === "CUT_LOSS" || action === "TAKE_PROFIT") {
      const qty = workflow === "Cognitive" ? (e.quantity || 0) : (e.quantity || 0) * 100;
      if (qty > 0 && totalQty > 0) {
        // Reduce investment proportionally
        const avgPrice = totalInvest / totalQty;
        totalInvest -= avgPrice * qty;
        totalQty -= qty;
        
        // Reset if all shares sold
        if (totalQty <= 0) {
          totalInvest = 0;
          totalQty = 0;
        }
      }
    }
  }

  if (totalQty <= 0) return null;
  return totalInvest / totalQty;
}

function getSellProfitFlag(entry: LedgerEntry, entries: LedgerEntry[], index: number): boolean {
  const sold = typeof entry.sold_amount === "number" ? entry.sold_amount : undefined;
  const realizedPnl = typeof (entry as any).realized_pnl === "number" ? (entry as any).realized_pnl : undefined;
  const pnl = typeof (entry as any).pnl === "number" ? (entry as any).pnl : undefined;
  const costBasis = typeof (entry as any).cost_basis === "number" ? (entry as any).cost_basis : undefined;

  // Priority 1: Use explicit PnL fields if available
  if (typeof realizedPnl === "number") return realizedPnl > 0;
  if (typeof pnl === "number") return pnl > 0;
  if (typeof sold === "number" && typeof costBasis === "number") return sold - costBasis > 0;

  // Priority 2: Calculate from average buy price
  const workflow = normalizeWorkflowName(entry);
  const avgBuy = getAvgBuyFromLedger(entries, index, entry.ticker, workflow);
  
  if (typeof sold === "number" && avgBuy !== null && entry.quantity !== undefined && entry.quantity > 0) {
    const shares = workflow === "Cognitive" ? entry.quantity : entry.quantity * 100;
    const costTotal = avgBuy * shares;
    const profit = sold - costTotal;
    return profit > 0;
  }

  // Priority 3: Use current price vs average buy (fallback)
  if (avgBuy !== null && entry.price !== undefined && entry.quantity !== undefined && entry.quantity > 0) {
    return entry.price > avgBuy;
  }

  return false;
}

export default function CandlestickChart({
  candles,
  ticker,
  ledgers,
  playbackDate,
  visibleDays,
}: {
  candles: Candle[];
  ticker: string;
  ledgers: any;
  playbackDate?: string;
  visibleDays?: number | null;
}) {
  const chartMarkers = useMemo(() => {
    const markers: Marker[] = [];

    let entries: LedgerEntry[] = [];
    if (Array.isArray(ledgers)) {
      entries = ledgers;
    } else if (ledgers && typeof ledgers === "object") {
      entries = Object.values(ledgers).flat() as LedgerEntry[];
    }

    const filtered = entries.filter((e) => {
      if (!e || e.ticker !== ticker) return false;
      if (playbackDate) {
        const d = (e.date || "").slice(0, 10);
        return d <= playbackDate;
      }
      return true;
    });

    filtered.forEach((entry, idx) => {
      const date = (entry.date || "").slice(0, 10);
      const code = normalizeWorkflowCode(entry);
      const action = (entry.action || "").toUpperCase();
      const idBase = `${action}-${code}-${date}-${idx}`;

      const isBuy = action === "BUY" || action === "BUY_MORE";
      const isSell = action === "SELL" || action === "TRIMMING" || action === "CUT_LOSS" || action === "TAKE_PROFIT";
      if (!isBuy && !isSell) return;

      if (!entry.quantity || entry.quantity === 0) return;

      const investAmt = (entry.invest_amount || 0) as number;
      const wfName = (entry.workflow || "") as string;

      if (isBuy) {
        markers.push({
          time: date,
          position: "belowBar",
          color: "#FAAD14",
          text: code,
          id: idBase,
          investedAmount: investAmt,
          workflow: wfName,
        });
        return;
      }

      const profitFlag = getSellProfitFlag(entry, filtered, idx);

      markers.push({
        time: date,
        position: "aboveBar",
        color: profitFlag ? "#10A37F" : "#EF4444",
        text: code,
        id: idBase,
        investedAmount: investAmt,
        workflow: wfName,
      });
    });

    return markers;
  }, [ticker, ledgers, playbackDate]);

  return (
    <div className="w-full flex flex-col">
      <div className="mb-5 flex flex-col gap-2 px-2">
        <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">Ghi chú đọc biểu đồ</div>
        <div className="max-w-4xl text-sm leading-6 text-[#666666]">
          Dữ liệu nến được lấy từ cơ sở dữ liệu thị trường đã lưu. Các marker thể hiện hành động giao dịch của Workflow đối với mã đang chọn tại hoặc trước mốc playback hiện tại.
        </div>
      </div>
      <LightweightChart candles={candles} markers={chartMarkers} visibleDays={visibleDays} />
    </div>
  );
}
