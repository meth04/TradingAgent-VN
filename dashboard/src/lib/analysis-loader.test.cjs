const fs = require("fs");
const os = require("os");
const path = require("path");
const test = require("node:test");
const assert = require("node:assert/strict");
const { loadWorkflowTickerAnalysis } = require("./analysis-loader.cjs");

test("loadWorkflowTickerAnalysis returns structured non-cognitive payload when artifacts exist", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "analysis-loader-"));
  fs.mkdirSync(path.join(root, "2026-01-06", "FPT", "kelly"), { recursive: true });
  fs.mkdirSync(path.join(root, "ledgers", "2026-01-06"), { recursive: true });

  fs.writeFileSync(
    path.join(root, "2026-01-06", "FPT", "kelly", "tier3_cio_decision.json"),
    JSON.stringify({ action: "BUY_MORE", weight_pct: 12.5, reasoning: "Strong setup" }),
    "utf8",
  );
  fs.writeFileSync(
    path.join(root, "2026-01-06", "FPT", "kelly", "tier2_debate_transcript.txt"),
    "Bull case vs bear case",
    "utf8",
  );
  fs.writeFileSync(
    path.join(root, "ledgers", "2026-01-06", "Kelly.json"),
    JSON.stringify([{ ticker: "FPT", action: "BUY_MORE", target_weight_pct: 12.5 }]),
    "utf8",
  );

  const analysis = loadWorkflowTickerAnalysis(root, "2026-01-06", "FPT", "kelly");
  assert.ok(analysis);
  assert.equal(analysis.workflow, "Kelly");
  assert.equal(analysis.ticker, "FPT");
  assert.equal(analysis.cio.action, "BUY_MORE");
  assert.equal(analysis.ledger.action, "BUY_MORE");
  assert.equal(analysis.debate_transcript, "Bull case vs bear case");
});

test("loadWorkflowTickerAnalysis returns null when structured artifacts are absent", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "analysis-loader-miss-"));
  const analysis = loadWorkflowTickerAnalysis(root, "2026-01-06", "FPT", "kelly");
  assert.equal(analysis, null);
});
