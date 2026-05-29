/* eslint-disable @typescript-eslint/no-require-imports */
const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");
const assert = require("node:assert/strict");
const ts = require("typescript");

function loadComputeModuleFromTemp(root) {
  const libPath = path.join(root, "dashboard", "src", "lib", "compute.ts");
  const source = fs.readFileSync(libPath, "utf8");
  const transformed = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText;

  const outPath = path.join(root, "dashboard", "src", "lib", "compute.test.module.cjs");
  fs.writeFileSync(outPath, `${transformed}\nmodule.exports = { computeLeaderboardForDate };\n`, "utf8");
  return require(outPath);
}

test("computeLeaderboardForDate prefers authoritative realized sell data for leaderboard sell metrics", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-compute-"));
  const dashboardLibDir = path.join(tempRoot, "dashboard", "src", "lib");
  fs.mkdirSync(dashboardLibDir, { recursive: true });
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/compute.ts", path.join(dashboardLibDir, "compute.ts"));

  const { computeLeaderboardForDate } = loadComputeModuleFromTemp(tempRoot);
  const rows = computeLeaderboardForDate(
    {
      Traditional: {
        cash: 1_000_000_000,
        positions: {
          AAA: { lots: [{ qty: 100, price: 100_000, days_held: 1 }] },
        },
        trades: 4,
        wins: 1,
        equity_history: [1_000_000_000, 1_010_000_000],
        last_date: "2026-01-06",
      },
    },
    {
      Traditional: [
        {
          ticker: "AAA",
          action: "SELL",
          price: 105_000,
          quantity: 1,
          sold_amount: 20_000_000,
          cost_basis: 9_500_000,
          realized_pnl: 1_250_000,
          workflow: "Traditional",
          date: "2026-01-05",
        },
        {
          ticker: "AAA",
          action: "TRIMMING",
          price: 95_000,
          quantity: 1,
          sold_amount: 8_800_000,
          cost_basis: 9_000_000,
          workflow: "Traditional",
          date: "2026-01-06",
        },
      ],
    },
    1,
  );

  assert.equal(rows.length, 1);
  assert.equal(rows[0].biggestWin, 1_250_000);
  assert.equal(rows[0].biggestLoss, -200_000);
  assert.equal(rows[0].profitFactor, 6.25);
  assert.equal(rows[0].winRate, 50);
});

test("computeLeaderboardForDate falls back to legacy inferred sell pnl when authoritative fields are absent", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-compute-fallback-"));
  const dashboardLibDir = path.join(tempRoot, "dashboard", "src", "lib");
  fs.mkdirSync(dashboardLibDir, { recursive: true });
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/compute.ts", path.join(dashboardLibDir, "compute.ts"));

  const { computeLeaderboardForDate } = loadComputeModuleFromTemp(tempRoot);
  const rows = computeLeaderboardForDate(
    {
      Traditional: {
        cash: 1_000_000_000,
        positions: {
          AAA: { lots: [{ qty: 100, price: 100_000, days_held: 1 }] },
        },
        trades: 1,
        wins: 0,
        equity_history: [1_000_000_000],
        last_date: "2026-01-05",
      },
    },
    {
      Traditional: [
        {
          ticker: "AAA",
          action: "SELL",
          price: 101_000,
          quantity: 1,
          sold_amount: 10_500_000,
          workflow: "Traditional",
          date: "2026-01-05",
        },
      ],
    },
    0,
  );

  assert.equal(rows[0].biggestWin, 500_000);
  assert.equal(rows[0].biggestLoss, 0);
  assert.equal(rows[0].profitFactor, 999);
});

test("computeLeaderboardForDate uses closed sells for win rate instead of total trades", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-compute-winrate-"));
  const dashboardLibDir = path.join(tempRoot, "dashboard", "src", "lib");
  fs.mkdirSync(dashboardLibDir, { recursive: true });
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/compute.ts", path.join(dashboardLibDir, "compute.ts"));

  const { computeLeaderboardForDate } = loadComputeModuleFromTemp(tempRoot);
  const rows = computeLeaderboardForDate(
    {
      Traditional: {
        cash: 1_000_000_000,
        positions: {},
        trades: 4,
        wins: 1,
        sells: 2,
        equity_history: [1_000_000_000, 1_005_000_000],
        last_date: "2026-01-06",
      },
    },
    { Traditional: [] },
    1,
  );

  assert.equal(rows[0].winRate, 50);
});

test("computeLeaderboardForDate derives win rate from ledger when state wins are stale", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "dashboard-compute-cognitive-winrate-"));
  const dashboardLibDir = path.join(tempRoot, "dashboard", "src", "lib");
  fs.mkdirSync(dashboardLibDir, { recursive: true });
  fs.cpSync("/home/vnn04/Documents/sandbox/dashboard/src/lib/compute.ts", path.join(dashboardLibDir, "compute.ts"));

  const { computeLeaderboardForDate } = loadComputeModuleFromTemp(tempRoot);
  const rows = computeLeaderboardForDate(
    {
      Cognitive: {
        cash: 1_000_000_000,
        positions: {},
        trades: 3,
        wins: 0,
        sells: 2,
        equity_history: [1_000_000_000, 1_010_000_000],
        last_date: "2026-01-06",
      },
    },
    {
      Cognitive: [
        {
          ticker: "AAA",
          action: "SELL",
          price: 101_000,
          quantity: 100,
          sold_amount: 10_500_000,
          cost_basis: 9_000_000,
          workflow: "Cognitive",
          date: "2026-01-05",
        },
        {
          ticker: "BBB",
          action: "TRIMMING",
          price: 95_000,
          quantity: 100,
          sold_amount: 8_800_000,
          cost_basis: 9_200_000,
          workflow: "Cognitive",
          date: "2026-01-06",
        },
      ],
    },
    1,
  );

  assert.equal(rows[0].winRate, 50);
});
