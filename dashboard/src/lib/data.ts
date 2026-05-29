import fs from "fs";
import path from "path";

const ROOT = path.join(process.cwd(), "../backtest_results");
const STATE_DIR = path.join(ROOT, "state");
const BLOG_DIR = path.join(ROOT, "blog_posts");
const LEDGER_DIR = path.join(ROOT, "ledgers");
const NORMALIZED_DIR = path.join(ROOT, "normalized");

export type PortfolioState = {
  cash: number;
  positions: Record<string, unknown>;
  trades: number;
  wins: number;
  sells?: number;
  equity_history: number[];
  last_date: string;
  buys_per_ticker?: Record<string, number>;
};

export type BlogPost = {
  date: string;
  workflow: string;
  filename: string;
  content: string;
};

export type LedgerEntry = {
  ticker: string;
  action: string;
  price: number;
  quantity?: number;
  sold_amount?: number;
  invest_amount?: number;
  workflow: string;
  date: string;
  current_weight_pct?: number;
  target_weight_pct?: number;
  equity_snapshot?: number;
  verdict?: string;
  net_score?: number;
};

export type CognitiveCard = {
  agent_name: string;
  ticker: string;
  action: string;
  confidence_calibrated: number;
  reasoning: string;
  evidence_ids: string[];
  analysis_steps?: string[];
  _thought_process?: string[];
};

export type CIODecision = {
  ticker: string;
  action: string;
  weight_pct: number;
  confidence?: number;
  reasoning: string;
};

function safeReadJSON<T>(filePath: string): T | null {
  try {
    let raw = fs.readFileSync(filePath, "utf8");
    raw = raw.replace(/:\s*Infinity/g, ": null");
    return JSON.parse(raw) as T;
  } catch (err) {
    console.error(`Failed to read ${filePath}`, err);
    return null;
  }
}

function toDisplayWorkflow(workflow: string): string {
  const lower = workflow.trim().toLowerCase();
  if (lower === "traditional") return "Traditional";
  if (lower === "kelly") return "Kelly";
  if (lower === "markowitz") return "Markowitz";
  if (lower === "cognitive") return "Cognitive";
  return workflow;
}

function normalizedArtifactPath(date: string, workflow: string, ticker?: string): string | null {
  const workflowLower = workflow.trim().toLowerCase();
  if (workflowLower === "cognitive") {
    return path.join(ROOT, "cognitive", "daily", date, "normalized", "workflow_artifact.json");
  }
  if (!ticker) return path.join(NORMALIZED_DIR, date, `${workflowLower}_workflow_artifact.json`);
  return path.join(ROOT, date, ticker, workflowLower, "normalized", "workflow_artifact.json");
}

function readNormalizedArtifact(date: string, workflow: string, ticker?: string): any | null {
  const workflowLower = workflow.trim().toLowerCase();
  const primaryPath = normalizedArtifactPath(date, workflow, ticker);
  if (primaryPath && fs.existsSync(primaryPath)) {
    return safeReadJSON<any>(primaryPath);
  }
  if (workflowLower !== "cognitive" && ticker) {
    const legacyDateLevelPath = path.join(ROOT, date, "normalized", `${workflowLower}_workflow_artifact.json`);
    if (fs.existsSync(legacyDateLevelPath)) {
      return safeReadJSON<any>(legacyDateLevelPath);
    }
  }
  return null;
}

export function loadStates(): Record<string, PortfolioState> {
  const result: Record<string, PortfolioState> = {};
  if (fs.existsSync(STATE_DIR)) {
    const files = fs.readdirSync(STATE_DIR).filter((f) => f.endsWith(".json"));
    for (const file of files) {
      const name = path.parse(file).name;
      const data = safeReadJSON<PortfolioState>(path.join(STATE_DIR, file));
      if (data) result[name] = data;
    }
  }
  const cogFile = path.join(ROOT, "cognitive", "state", "portfolio.json");
  if (fs.existsSync(cogFile)) {
    const data = safeReadJSON<PortfolioState>(cogFile);
    if (data) result["Cognitive"] = data;
  }
  return result;
}

export function loadBlogPosts(): BlogPost[] {
  const posts: BlogPost[] = [];

  if (fs.existsSync(BLOG_DIR)) {
    const files = fs.readdirSync(BLOG_DIR).filter((f) => f.endsWith(".md"));
    for (const file of files) {
      const match = file.match(/^(\d{4}-\d{2}-\d{2})_(\w+)_Daily_Report\.md$/);
      if (!match) continue;
      const [, date, workflow] = match;
      const content = fs.readFileSync(path.join(BLOG_DIR, file), "utf8");
      posts.push({ date, workflow, filename: file, content });
    }
  }

  const cogDailyDir = path.join(ROOT, "cognitive", "daily");
  if (fs.existsSync(cogDailyDir)) {
    const dirs = fs.readdirSync(cogDailyDir).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d));
    for (const date of dirs) {
      const reportFile = path.join(cogDailyDir, date, "daily_report.md");
      if (fs.existsSync(reportFile)) {
        const content = fs.readFileSync(reportFile, "utf8");
        posts.push({ date, workflow: "Cognitive", filename: `${date}_Cognitive_Daily_Report.md`, content });
      }
    }
  }

  return posts.sort((a, b) => (a.date === b.date ? a.workflow.localeCompare(b.workflow) : b.date.localeCompare(a.date)));
}

export function listLedgerDates(): string[] {
  const dateSet = new Set<string>();

  if (fs.existsSync(LEDGER_DIR)) {
    fs.readdirSync(LEDGER_DIR)
      .filter((entry) => /^\d{4}-\d{2}-\d{2}$/.test(entry))
      .forEach((d) => dateSet.add(d));
  }

  const cogLedgerDir = path.join(ROOT, "cognitive", "ledgers");
  if (fs.existsSync(cogLedgerDir)) {
    fs.readdirSync(cogLedgerDir)
      .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f))
      .forEach((f) => dateSet.add(f.replace(".json", "")));
  }

  return Array.from(dateSet).sort();
}

function normalizeCognitiveEntries(raw: any[]): LedgerEntry[] {
  return raw
    .filter((e) => {
      if ((e.status === "BLOCKED" || e.status === "NO_ACTION") && (e.quantity === 0 || !e.quantity)) {
        return false;
      }
      if ((e.action === "PASS" || e.action === "HOLD") && (e.quantity === 0 || !e.quantity)) {
        return false;
      }
      return true;
    })
    .map((e) => {
      const isSell = e.action === "SELL" || e.action === "TRIMMING" || e.action === "CUT_LOSS" || e.action === "TAKE_PROFIT";
      return {
        ticker: e.ticker,
        action: e.action,
        price: e.price,
        quantity: e.quantity,
        invest_amount: isSell ? undefined : (e.total_cost ?? e.invest_amount),
        sold_amount: isSell ? (e.total_cost ?? e.sold_amount) : undefined,
        workflow: "Cognitive",
        date: e.date,
        current_weight_pct: e.weight_pct,
        target_weight_pct: e.weight_pct,
        confidence: e.confidence,
      } as LedgerEntry;
    });
}

export function loadLedgersForDate(date: string): Record<string, LedgerEntry[]> {
  const result: Record<string, LedgerEntry[]> = {};
  const dir = path.join(LEDGER_DIR, date);
  if (fs.existsSync(dir)) {
    const files = fs.readdirSync(dir).filter((f) => f.endsWith(".json"));
    for (const file of files) {
      const workflow = path.parse(file).name;
      const data = safeReadJSON<LedgerEntry[]>(path.join(dir, file));
      if (data) result[workflow] = data;
    }
  }
  const cogFile = path.join(ROOT, "cognitive", "ledgers", `${date}.json`);
  if (fs.existsSync(cogFile)) {
    const raw = safeReadJSON<any[]>(cogFile);
    if (raw) result["Cognitive"] = normalizeCognitiveEntries(raw);
  }
  return result;
}

export function loadAllLedgers(): Record<string, Record<string, LedgerEntry[]>> {
  const dates = listLedgerDates();
  const map: Record<string, Record<string, LedgerEntry[]>> = {};
  dates.forEach((date) => {
    map[date] = loadLedgersForDate(date);
  });
  return map;
}

export function getPlaybackDates(states: Record<string, PortfolioState>): string[] {
  const ledgerDates = listLedgerDates();
  const equityDates = new Set<string>();
  Object.values(states).forEach((state) => {
    if (state.last_date) equityDates.add(state.last_date);
  });
  const merged = Array.from(new Set([...ledgerDates, ...Array.from(equityDates)])).sort();
  return merged;
}

export type Summary = {
  workflow: string;
  start: string;
  end: string;
  trading_days: number;
  metrics: {
    account_value: number;
    return_pct: number;
    annualized_return_pct: number;
    total_pnl: number;
    win_rate: number;
    daily_win_rate: number;
    sharpe: number;
    max_drawdown_pct: number;
    trades: number;
  };
  benchmarks: Record<string, { strategy_return_pct: number; benchmark_return_pct: number }>;
};

const summaryLoader = require("./summary-loader.cjs");

function stripReasoningTags(value: unknown): string {
  return String(value || "")
    .replace(/<(think|thinking)>[\s\S]*?<\/(think|thinking)>/gi, "")
    .replace(/<\/?(think|thinking)>/gi, "")
    .replace(/&lt;(think|thinking)&gt;[\s\S]*?&lt;\/(think|thinking)&gt;/gi, "")
    .replace(/&lt;\/?(think|thinking)&gt;/gi, "")
    .trim();
}

export function loadSummary(workflow: string): Summary | null {
  return summaryLoader.loadSummary(ROOT, workflow) as Summary | null;
}

export function loadSummaries(): Summary[] {
  return summaryLoader.loadSummaries(ROOT) as Summary[];
}

export function loadReflection() {
  const file = path.join(ROOT, "cognitive", "reflection_summary.md");
  if (!fs.existsSync(file)) return null;
  return fs.readFileSync(file, "utf8");
}

export function loadDailyAnalysis(date: string, ticker: string) {
  const normalized = readNormalizedArtifact(date, "cognitive", ticker);
  if (normalized?.analysis?.[ticker]) {
    const artifact = normalized.analysis[ticker];
    return {
      cards: (artifact.cards || []).map((card: any) => ({
        ...card,
        _thought_process: (card.analysis_steps || card._thought_process || []).map((step: unknown) => stripReasoningTags(step)).filter(Boolean),
        reasoning: stripReasoningTags(card.reasoning_summary || card.reasoning || ""),
        confidence_calibrated: card.confidence_calibrated,
      })),
      cio: artifact.cio_intent
        ? {
            ...artifact.cio_intent,
            reasoning: stripReasoningTags(artifact.cio_intent.reasoning),
          }
        : null,
      debate: artifact.debate
        ? {
            ...artifact.debate,
            transcript: stripReasoningTags(artifact.debate.transcript),
          }
        : null,
      metadata: artifact.metadata || {},
      normalized: true,
    };
  }

  const dir = path.join(ROOT, "cognitive", "daily", date, "analysis", ticker);
  if (!fs.existsSync(dir)) return null;
  const cards = safeReadJSON<CognitiveCard[]>(path.join(dir, "cards.json"));
  const cio = safeReadJSON<CIODecision>(path.join(dir, "cio_decision.json"));
  return { cards, cio, normalized: false };
}

export function loadWorkflowTickerAnalysis(date: string, ticker: string, workflow: string) {
  const normalized = readNormalizedArtifact(date, workflow, ticker);
  const workflowKey = toDisplayWorkflow(workflow);
  const analysisKeys = Object.keys(normalized?.analysis || {});
  const normalizedTickerKey =
    analysisKeys.find((key) => key.toUpperCase() === ticker.toUpperCase()) ||
    // Markowitz lưu kết quả ở cấp danh mục dưới khoá "MARKOWITZ_BASKET"
    // (không per-ticker), nên mọi ticker được chọn map về artifact basket này.
    (workflow.toLowerCase() === "markowitz"
      ? analysisKeys.find((key) => key.toUpperCase().includes("BASKET")) ||
        analysisKeys[0]
      : undefined);
  if (normalizedTickerKey) {
    const artifact = normalized.analysis[normalizedTickerKey];
    return {
      workflow: workflowKey,
      ticker: normalizedTickerKey,
      date,
      cards: (artifact.cards || []).map((card: any) => ({
        ...card,
        _thought_process: (card.analysis_steps || card._thought_process || []).map((step: unknown) => stripReasoningTags(step)).filter(Boolean),
        reasoning: stripReasoningTags(card.reasoning_summary || card.reasoning || ""),
        confidence_calibrated: card.confidence_calibrated,
      })),
      cio: artifact.cio_intent
        ? {
            ...artifact.cio_intent,
            reasoning: stripReasoningTags(artifact.cio_intent.reasoning),
          }
        : null,
      debate: artifact.debate
        ? {
            ...artifact.debate,
            transcript: stripReasoningTags(artifact.debate.transcript),
          }
        : null,
      ledger: artifact.trade || null,
      metadata: artifact.metadata || {},
      normalized: true,
      artifact_origin: artifact.artifact_origin || normalized.artifact_origin,
      analysis_depth: artifact.analysis_depth || normalized.analysis_depth,
    };
  }

  const workflowDir = path.join(ROOT, date, ticker, workflow.toLowerCase());
  if (!fs.existsSync(workflowDir)) return null;

  const cio = safeReadJSON<Record<string, unknown>>(path.join(workflowDir, "tier3_cio_decision.json"));
  const transcriptPath = path.join(workflowDir, "tier2_debate_transcript.txt");
  const debate_transcript = fs.existsSync(transcriptPath)
    ? fs.readFileSync(transcriptPath, "utf8")
    : null;

  const ledgers = loadLedgersForDate(date);
  const ledger = (ledgers[workflowKey] || []).find((entry) => entry.ticker === ticker) || null;

  if (!cio && !debate_transcript && !ledger) return null;

  return {
    workflow: workflowKey,
    ticker,
    date,
    cards: [],
    cio: cio
      ? {
          ...cio,
          reasoning: stripReasoningTags((cio as Record<string, unknown>).reasoning),
        }
      : null,
    debate: debate_transcript
      ? { triggered: true, transcript: stripReasoningTags(debate_transcript) }
      : null,
    ledger,
    normalized: false,
    artifact_origin: "legacy",
    analysis_depth: "sparse",
  };
}

export function listAnalysisDates(): string[] {
  const dates = new Set<string>();
  const cogDir = path.join(ROOT, "cognitive", "daily");
  if (fs.existsSync(cogDir)) {
    fs.readdirSync(cogDir).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)).forEach((d) => dates.add(d));
  }
  if (fs.existsSync(NORMALIZED_DIR)) {
    fs.readdirSync(NORMALIZED_DIR).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)).forEach((d) => dates.add(d));
  }
  return Array.from(dates).sort();
}
