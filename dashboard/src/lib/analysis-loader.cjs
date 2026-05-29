const fs = require("fs");
const path = require("path");

function safeReadJSON(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (_err) {
    return null;
  }
}

function loadLedgersForDate(root, date) {
  const result = {};
  const dir = path.join(root, "ledgers", date);
  if (fs.existsSync(dir)) {
    const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json"));
    for (const file of files) {
      const workflow = path.parse(file).name;
      const data = safeReadJSON(path.join(dir, file));
      if (data) result[workflow] = data;
    }
  }
  return result;
}

function loadWorkflowTickerAnalysis(root, date, ticker, workflow) {
  const workflowDir = path.join(root, date, ticker, workflow.toLowerCase());
  if (!fs.existsSync(workflowDir)) return null;

  const cio = safeReadJSON(path.join(workflowDir, "tier3_cio_decision.json"));
  const transcriptPath = path.join(workflowDir, "tier2_debate_transcript.txt");
  const debate_transcript = fs.existsSync(transcriptPath)
    ? fs.readFileSync(transcriptPath, "utf8")
    : null;

  const ledgers = loadLedgersForDate(root, date);
  const workflowKey = workflow.charAt(0).toUpperCase() + workflow.slice(1);
  const ledger = (ledgers[workflowKey] || []).find((entry) => entry.ticker === ticker) || null;

  if (!cio && !debate_transcript && !ledger) return null;

  return {
    workflow: workflowKey,
    ticker,
    date,
    cio,
    debate_transcript,
    ledger,
  };
}

module.exports = {
  loadWorkflowTickerAnalysis,
};
