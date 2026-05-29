const fs = require("fs");
const path = require("path");

function safeReadJSON(filePath) {
  try {
    let raw = fs.readFileSync(filePath, "utf8");
    raw = raw.replace(/:\s*Infinity/g, ": null");
    return JSON.parse(raw);
  } catch (_err) {
    return null;
  }
}

let cachedComparison = null;
function getComparisonMetrics(root) {
  if (cachedComparison) return cachedComparison;
  const compFile = path.join(root, "..", "evaluation_engine", "outputs", "workflow_metrics", "workflow_comparison.json");
  const data = safeReadJSON(compFile);
  if (Array.isArray(data)) {
    cachedComparison = {};
    data.forEach((entry) => {
      if (entry && entry.workflow) {
        const wf = String(entry.workflow).toLowerCase();
        cachedComparison[wf] = entry;
      }
    });
  }
  return cachedComparison;
}

function overrideWithThesisMetrics(summary, compEntry) {
  if (!summary || !compEntry) return summary;
  summary.start = compEntry.start_date || summary.start;
  summary.end = compEntry.end_date || summary.end;
  summary.trading_days = compEntry.observations || summary.trading_days;
  
  if (!summary.metrics) summary.metrics = {};
  summary.metrics.return_pct = compEntry.total_return_pct !== undefined ? compEntry.total_return_pct : summary.metrics.return_pct;
  summary.metrics.max_drawdown_pct = compEntry.max_drawdown_pct !== undefined ? compEntry.max_drawdown_pct : summary.metrics.max_drawdown_pct;
  summary.metrics.sharpe = compEntry.sharpe_proxy !== undefined ? compEntry.sharpe_proxy : summary.metrics.sharpe;
  summary.metrics.trades = compEntry.trade_count !== undefined ? compEntry.trade_count : summary.metrics.trades;
  summary.metrics.account_value = compEntry.final_nav !== undefined ? compEntry.final_nav : summary.metrics.account_value;
  summary.metrics.total_pnl = (compEntry.final_nav !== undefined && compEntry.start_nav !== undefined) ? (compEntry.final_nav - compEntry.start_nav) : summary.metrics.total_pnl;
  
  if (compEntry.sortino_proxy !== undefined) summary.metrics.sortino = compEntry.sortino_proxy;
  if (compEntry.calmar_proxy !== undefined) summary.metrics.calmar = compEntry.calmar_proxy;
  if (compEntry.volatility_ann_pct !== undefined) summary.metrics.volatility = compEntry.volatility_ann_pct;
  
  return summary;
}

function loadSummary(root, workflow) {
  const file = path.join(root, "evaluation", workflow.toLowerCase(), "summary.json");
  const summary = safeReadJSON(file);
  if (summary) {
    const comp = getComparisonMetrics(root);
    const wfKey = workflow.toLowerCase();
    if (comp && comp[wfKey]) {
      overrideWithThesisMetrics(summary, comp[wfKey]);
    }
  }
  return summary;
}

function cognitiveClosingTradeStats(root) {
  const ledgersDir = path.join(root, "cognitive", "ledgers");
  if (!fs.existsSync(ledgersDir)) {
    return { closedTrades: 0, winningClosedTrades: 0 };
  }

  let closedTrades = 0;
  let winningClosedTrades = 0;
  const lotsByTicker = new Map();
  const sortedFiles = fs.readdirSync(ledgersDir).sort();

  function getLots(ticker) {
    if (!lotsByTicker.has(ticker)) lotsByTicker.set(ticker, []);
    return lotsByTicker.get(ticker);
  }

  for (const fileName of sortedFiles) {
    const filePath = path.join(ledgersDir, fileName);
    const entries = safeReadJSON(filePath);
    if (!Array.isArray(entries)) continue;
    for (const entry of entries) {
      const ticker = String(entry?.ticker || "").toUpperCase();
      const action = String(entry?.action || "").toUpperCase();
      const quantity = Number(entry?.quantity ?? 0);
      const price = Number(entry?.price ?? 0);
      const lots = getLots(ticker);

      if ((action === "BUY" || action === "BUY_MORE") && quantity > 0 && price > 0) {
        lots.push({ qty: quantity, price });
        continue;
      }

      const isClosing = action.includes("SELL") || action === "TRIMMING" || action === "CUT_LOSS" || action === "TAKE_PROFIT";
      if (!isClosing) continue;
      closedTrades += 1;

      let pnl = null;
      if (typeof entry.realized_pnl === "number") {
        pnl = entry.realized_pnl;
      } else if (typeof entry.sold_amount === "number" && typeof entry.cost_basis === "number") {
        pnl = entry.sold_amount - entry.cost_basis;
      } else {
        const proceeds = typeof entry.sold_amount === "number"
          ? entry.sold_amount
          : (typeof entry.total_cost === "number" ? entry.total_cost : null);
        if (typeof proceeds === "number" && quantity > 0 && lots.length > 0) {
          let remaining = quantity;
          let costBasis = 0;
          while (remaining > 0 && lots.length > 0) {
            const current = lots[0];
            const used = Math.min(current.qty, remaining);
            costBasis += used * current.price;
            current.qty -= used;
            remaining -= used;
            if (current.qty <= 0) lots.shift();
          }
          pnl = proceeds - costBasis;
        }
      }

      if (typeof pnl === "number" && pnl > 0) {
        winningClosedTrades += 1;
      }
    }
  }

  return { closedTrades, winningClosedTrades };
}

function loadCognitiveSummary(root) {
  const benchmarkFile = path.join(root, "cognitive", "state", "benchmark_metrics.json");
  const portfolioFile = path.join(root, "cognitive", "state", "portfolio.json");
  const equityCurveFile = path.join(root, "cognitive", "equity_curve.json");

  const benchmarkMetrics = safeReadJSON(benchmarkFile);
  const portfolio = safeReadJSON(portfolioFile);
  const equityCurve = safeReadJSON(equityCurveFile);

  if (!portfolio || !equityCurve || equityCurve.length === 0) return null;

  const start = equityCurve[0]?.date;
  const end = equityCurve[equityCurve.length - 1]?.date;
  if (!start || !end) return null;

  const finalEquity = Number(equityCurve[equityCurve.length - 1]?.equity ?? 0);
  const startCapital = 1_000_000_000;
  const totalPnl = finalEquity - startCapital;
  const returnPct = startCapital > 0 ? (totalPnl / startCapital) * 100 : 0;
  const trades = Number(portfolio.trades ?? 0);
  const ledgerStats = cognitiveClosingTradeStats(root);
  const closedTrades = ledgerStats.closedTrades > 0 ? ledgerStats.closedTrades : Number(portfolio.sells ?? 0);
  const wins = ledgerStats.closedTrades > 0 ? ledgerStats.winningClosedTrades : Number(portfolio.wins ?? 0);
  const winRate = closedTrades > 0 ? (wins / closedTrades) * 100 : 0;

  const summary = {
    workflow: "Cognitive",
    start,
    end,
    trading_days: equityCurve.length,
    metrics: {
      account_value: finalEquity,
      return_pct: returnPct,
      annualized_return_pct: 0,
      total_pnl: totalPnl,
      win_rate: winRate,
      daily_win_rate: 0,
      sharpe: 0,
      max_drawdown_pct: 0,
      trades,
    },
    benchmarks: benchmarkMetrics ?? {},
  };

  const comp = getComparisonMetrics(root);
  if (comp && comp["cognitive"]) {
    overrideWithThesisMetrics(summary, comp["cognitive"]);
  }
  return summary;
}

function loadSummaries(root) {
  const workflows = ["traditional", "kelly", "markowitz"];
  const summaries = [];
  workflows.forEach((wf) => {
    const s = loadSummary(root, wf);
    if (s) summaries.push(s);
  });

  const cognitive = loadCognitiveSummary(root);
  if (cognitive) summaries.push(cognitive);

  return summaries;
}

module.exports = {
  loadSummary,
  loadCognitiveSummary,
  loadSummaries,
};
