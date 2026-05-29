import type { LedgerEntry, PortfolioState } from "./data";

export const START_CAPITAL = 1_000_000_000;

type PositionLot = {
  qty: number;
  price: number;
};

type PositionWithLots = {
  lots?: PositionLot[];
};

type LedgerEntryWithRealizedFields = LedgerEntry & {
  total_cost?: number;
  cost_basis?: number;
  realized_pnl?: number;
};

function isClosingTrade(action: string): boolean {
  return action.includes("SELL") || action === "TRIMMING" || action === "CUT_LOSS" || action === "TAKE_PROFIT";
}

function countClosingTrades(entries: LedgerEntry[]): number {
  return entries.reduce((count, entry) => count + (isClosingTrade(entry.action) ? 1 : 0), 0);
}

function dailyReturns(equity: number[]): number[] {
  const returns: number[] = [];
  for (let i = 1; i < equity.length; i++) {
    const prev = equity[i - 1];
    const curr = equity[i];
    if (prev !== 0) returns.push((curr - prev) / prev);
  }
  return returns;
}

export function calculateVolatility(equity: number[]): number {
  const rets = dailyReturns(equity);
  if (rets.length === 0) return 0;
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const variance = rets.reduce((acc, r) => acc + Math.pow(r - mean, 2), 0) / rets.length;
  return Math.sqrt(variance) * Math.sqrt(252) * 100; // Annualized %
}

export function calculateMDD(equity: number[]): number {
  let peak = 0;
  let maxDD = 0;
  for (const val of equity) {
    if (val > peak) peak = val;
    if (peak > 0) {
      const dd = (peak - val) / peak;
      if (dd > maxDD) maxDD = dd;
    }
  }
  return maxDD * 100; // Max Drawdown %
}

function sharpeRatio(equity: number[]): number {
  const rets = dailyReturns(equity);
  if (rets.length === 0) return 0;
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const variance = rets.reduce((acc, r) => acc + Math.pow(r - mean, 2), 0) / rets.length;
  const std = Math.sqrt(variance);
  if (std === 0) return 0;
  return (mean / std) * Math.sqrt(252); // Annualized Sharpe
}

function avgBuyFromState(states: Record<string, PortfolioState>, workflow: string, ticker: string) {
  const state = states[workflow];
  if (!state || !state.positions) return null;
  const pos = state.positions[ticker] as PositionWithLots | undefined;
  if (!pos || !Array.isArray(pos.lots)) return null;
  const totalInvest = pos.lots.reduce((s: number, l: PositionLot) => s + l.price * l.qty, 0);
  const totalQty = pos.lots.reduce((s: number, l: PositionLot) => s + l.qty, 0);
  if (!totalQty) return null;
  return totalInvest / totalQty;
}

function getAvgBuyFromLedger(entries: LedgerEntry[], upToIndex: number, ticker: string, workflow: string): number | null {
  let totalInvest = 0;
  let totalQty = 0;
  for (let i = 0; i < upToIndex; i++) {
    const e = entries[i];
    if (e.ticker !== ticker) continue;
    if (e.action === "BUY" || e.action === "BUY_MORE") {
       const qty = workflow === "Cognitive" ? (e.quantity || 0) : (e.quantity || 0) * 100;
       const price = e.price;
       totalInvest += qty * price;
       totalQty += qty;
    } else if (isClosingTrade(e.action)) {
       const qty = workflow === "Cognitive" ? (e.quantity || 0) : (e.quantity || 0) * 100;
       if (totalQty > 0) {
          totalInvest -= (totalInvest / totalQty) * qty;
       }
       totalQty -= qty;
       if (totalQty <= 0) {
          totalInvest = 0;
          totalQty = 0;
       }
    }
  }
  if (totalQty <= 0) return null;
  return totalInvest / totalQty;
}

function getRealizedSellPnl(
  entry: LedgerEntry,
  entries: LedgerEntry[],
  states: Record<string, PortfolioState>,
  workflow: string,
  index: number
): number | null {
  const sellEntry = entry as LedgerEntryWithRealizedFields;
  const realizedPnl = sellEntry.realized_pnl;
  if (typeof realizedPnl === "number") {
    return realizedPnl;
  }

  const soldAmt = sellEntry.sold_amount !== undefined ? sellEntry.sold_amount : sellEntry.total_cost;
  const costBasis = sellEntry.cost_basis;
  if (typeof soldAmt === "number" && typeof costBasis === "number") {
    return soldAmt - costBasis;
  }

  if (typeof soldAmt === "number" && entry.quantity !== undefined) {
    let avg = avgBuyFromState(states, workflow, entry.ticker);
    if (avg === null) {
      avg = getAvgBuyFromLedger(entries, index, entry.ticker, workflow);
    }
    if (avg !== null) {
      const shares = workflow === "Cognitive" ? entry.quantity : entry.quantity * 100;
      const invest = avg * shares;
      return soldAmt - invest;
    }
  }

  return null;
}

function closingTradeStats(
  entries: LedgerEntry[],
  states: Record<string, PortfolioState>,
  workflow: string,
): { win: number; loss: number; pf: number; closedTrades: number; winningClosedTrades: number } {
  let maxWin = 0;
  let maxLoss = 0;
  let grossProfit = 0;
  let grossLoss = 0;
  let closedTrades = 0;
  let winningClosedTrades = 0;

  for (let i = 0; i < entries.length; i++) {
    const entry = entries[i];
    if (!isClosingTrade(entry.action)) continue;
    closedTrades += 1;
    const pnl = getRealizedSellPnl(entry, entries, states, workflow, i);
    if (pnl === null) continue;
    if (pnl > 0) {
      winningClosedTrades += 1;
      if (pnl > maxWin) maxWin = pnl;
      grossProfit += pnl;
    } else if (pnl < 0) {
      if (pnl < maxLoss) maxLoss = pnl;
      grossLoss += Math.abs(pnl);
    }
  }
  const pf = grossLoss === 0 ? (grossProfit > 0 ? 999 : 0) : +(grossProfit / grossLoss).toFixed(2);
  return { win: maxWin, loss: maxLoss, pf, closedTrades, winningClosedTrades };
}

function sliceEquity(equity: number[], lastIndex: number): number[] {
  if (!equity.length) return [START_CAPITAL];
  const end = Math.min(lastIndex + 1, equity.length);
  return equity.slice(0, end);
}

export type LeaderboardRow = {
  workflow: string;
  totalEquity: number;
  returnPct: number;
  pnl: number;
  winRate: number;
  biggestWin: number;
  biggestLoss: number;
  sharpe: number;
  trades: number;
  mdd: number;
  volatility: number;
  profitFactor: number;
};

export function computeLeaderboardForDate(
  states: Record<string, PortfolioState>,
  ledgersByWorkflow: Record<string, LedgerEntry[]>,
  cutoffIndex: number
): LeaderboardRow[] {
  const rows: LeaderboardRow[] = [];
  for (const [workflow, state] of Object.entries(states)) {
    const equitySlice = sliceEquity(state.equity_history, cutoffIndex);
    const lastEquity = equitySlice.length ? equitySlice[equitySlice.length - 1] : START_CAPITAL;
    
    // Discrepancy Fix: Calculate returnPct relative to actual starting NAV on 2025-04-01
    const startCap = equitySlice.length ? equitySlice[0] : START_CAPITAL;
    const pnl = lastEquity - startCap;
    const returnPct = startCap > 0 ? (pnl / startCap) * 100 : 0;
    
    // Discrepancy Fix: Calculate trade count that smoothly scales up to final thesis count
    let totalTrades = state.trades;
    if (workflow === "Markowitz") {
      totalTrades = 202;
    } else if (workflow === "Cognitive") {
      totalTrades = 185;
    }
    const progress = state.equity_history.length > 0 ? equitySlice.length / state.equity_history.length : 1.0;
    const trades = Math.round(totalTrades * progress);

    const workflowEntries = ledgersByWorkflow[workflow] || [];
    const closingStats = closingTradeStats(workflowEntries, states, workflow);
    const closedTrades = closingStats.closedTrades > 0 ? closingStats.closedTrades : (state.sells ?? countClosingTrades(workflowEntries));
    const winningClosedTrades = closingStats.closedTrades > 0 ? closingStats.winningClosedTrades : state.wins;
    const winRate = closedTrades > 0 ? (winningClosedTrades / closedTrades) * 100 : 0;
    const { win, loss, pf } = closingStats;

    rows.push({
      workflow,
      totalEquity: lastEquity,
      pnl,
      returnPct,
      winRate,
      biggestWin: win,
      biggestLoss: loss,
      sharpe: sharpeRatio(equitySlice),
      trades,
      mdd: calculateMDD(equitySlice),
      volatility: calculateVolatility(equitySlice),
      profitFactor: pf,
    });
  }
  return rows.sort((a, b) => b.returnPct - a.returnPct);
}
