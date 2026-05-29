const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");
const assert = require("node:assert/strict");
const ts = require("typescript");

function loadModuleFromTemp(root) {
  return loadDataModuleWithExportsFromTemp(root, ["loadSummaries", "loadSummary"]);
}

function loadDataModuleWithExportsFromTemp(root, exportsList) {
  const libPath = path.join(root, "dashboard", "src", "lib", "data.ts");
  const source = fs.readFileSync(libPath, "utf8");
  const transformed = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  }).outputText;

  const outPath = path.join(root, "dashboard", "src", "lib", "data.test.module.cjs");
  fs.writeFileSync(outPath, `${transformed}\nmodule.exports = { ${exportsList.join(", ")} };\n`, "utf8");
  const previousCwd = process.cwd();
  process.chdir(path.join(root, "dashboard"));
  try {
    delete require.cache[require.resolve(outPath)];
    return require(outPath);
  } finally {
    process.chdir(previousCwd);
  }
}

test("loadSummaries preserves VNStock summaries and adds cognitive summary when present", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-data-"));
  const dashboardLibDir = path.join(tempRoot, "dashboard", "src", "lib");
  const backtestRoot = path.join(tempRoot, "backtest_results");
  fs.mkdirSync(dashboardLibDir, { recursive: true });
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/data.ts", path.join(dashboardLibDir, "data.ts"));
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/summary-loader.cjs", path.join(dashboardLibDir, "summary-loader.cjs"));

  fs.mkdirSync(path.join(backtestRoot, "evaluation", "traditional"), { recursive: true });
  fs.writeFileSync(
    path.join(backtestRoot, "evaluation", "traditional", "summary.json"),
    JSON.stringify({
      workflow: "Traditional",
      start: "2026-01-05",
      end: "2026-01-06",
      trading_days: 2,
      metrics: {
        account_value: 1010000000,
        return_pct: 1,
        annualized_return_pct: 0,
        total_pnl: 10000000,
        win_rate: 50,
        daily_win_rate: 50,
        sharpe: 1.2,
        max_drawdown_pct: -1,
        trades: 2,
      },
      benchmarks: {},
    }),
    "utf8",
  );

  fs.mkdirSync(path.join(backtestRoot, "cognitive", "state"), { recursive: true });
  fs.writeFileSync(
    path.join(backtestRoot, "cognitive", "state", "portfolio.json"),
    JSON.stringify({ cash: 100000000, positions: {}, trades: 4, wins: 1, sells: 2, equity_history: [1000000000, 1020000000], last_date: "2026-01-06" }),
    "utf8",
  );
  fs.writeFileSync(
    path.join(backtestRoot, "cognitive", "equity_curve.json"),
    JSON.stringify([
      { date: "2026-01-05", equity: 1000000000 },
      { date: "2026-01-06", equity: 1020000000 },
    ]),
    "utf8",
  );
  fs.writeFileSync(
    path.join(backtestRoot, "cognitive", "state", "benchmark_metrics.json"),
    JSON.stringify({ VN30: { strategy_return_pct: 2, benchmark_return_pct: 1 } }),
    "utf8",
  );
  fs.mkdirSync(path.join(backtestRoot, "cognitive", "ledgers"), { recursive: true });
  fs.writeFileSync(
    path.join(backtestRoot, "cognitive", "ledgers", "2026-01-06.json"),
    JSON.stringify([
      { ticker: "AAA", action: "SELL", sold_amount: 11000000, cost_basis: 10000000 },
      { ticker: "BBB", action: "TRIMMING", sold_amount: 9000000, cost_basis: 9500000 }
    ]),
    "utf8",
  );

  const mod = loadModuleFromTemp(tempRoot);
  const summaries = mod.loadSummaries();

  assert.equal(summaries.some((s) => s.workflow === "Traditional"), true);
  const cognitive = summaries.find((s) => s.workflow === "Cognitive");
  assert.ok(cognitive);
  assert.equal(cognitive.metrics.account_value, 1020000000);
  assert.equal(cognitive.metrics.total_pnl, 20000000);
  assert.equal(cognitive.metrics.trades, 4);
  assert.equal(cognitive.metrics.win_rate, 50);
  assert.equal(cognitive.benchmarks.VN30.strategy_return_pct, 2);
});

test("loadWorkflowTickerAnalysis falls back to date-level normalized artifact for legacy workflows", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-data-"));
  const dashboardLibDir = path.join(tempRoot, "dashboard", "src", "lib");
  const backtestRoot = path.join(tempRoot, "backtest_results");
  fs.mkdirSync(dashboardLibDir, { recursive: true });
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/data.ts", path.join(dashboardLibDir, "data.ts"));
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/summary-loader.cjs", path.join(dashboardLibDir, "summary-loader.cjs"));

  fs.mkdirSync(path.join(backtestRoot, "2026-03-31", "normalized"), { recursive: true });
  fs.writeFileSync(
    path.join(backtestRoot, "2026-03-31", "normalized", "traditional_workflow_artifact.json"),
    JSON.stringify({
      version: "1.0",
      workflow: "traditional",
      analysis: {
        FPT: {
          artifact_origin: "adapted",
          analysis_depth: "sparse",
          cards: [],
          cio_intent: { action: "HOLD", reasoning: "fallback works" },
          debate: null,
          trade: null,
          metadata: { source: "date-level" },
        },
      },
    }),
    "utf8",
  );

  const mod = loadDataModuleWithExportsFromTemp(tempRoot, ["loadWorkflowTickerAnalysis"]);
  const analysis = mod.loadWorkflowTickerAnalysis("2026-03-31", "FPT", "Traditional");

  assert.ok(analysis);
  assert.equal(analysis.workflow, "Traditional");
  assert.equal(analysis.ticker, "FPT");
  assert.equal(analysis.cio.action, "HOLD");
  assert.equal(analysis.metadata.source, "date-level");
  assert.equal(analysis.normalized, true);
});
