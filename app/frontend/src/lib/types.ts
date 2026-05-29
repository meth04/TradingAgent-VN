export type AgentName = "macro" | "technical" | "quant" | "news" | "financial";

export type Workflow = "traditional" | "kelly" | "markowitz" | "cognitive";

export type Action = "BUY" | "BUY_MORE" | "SELL" | "TRIMMING" | "PASS" | "HOLD";

export type AgentStatus = "pending" | "running" | "completed" | "error";

export interface AgentResult {
  agent: AgentName;
  ticker: string;
  status: AgentStatus;
  output: string;
  confidence?: number | null;
  action?: Action | null;
  error?: string | null;
}

export interface CIOResult {
  ticker: string;
  action: Action;
  weight_pct: number;
  confidence: number;
  reasoning: string;
  debate_summary?: string;
}

export interface DoneResult {
  analysis_id: string;
  tickers: string[];
}

export type JobStatus = "running" | "done" | "error";

export type JobPhase = "init" | "crawl" | "agents" | "cio" | "report" | "done";

export interface JobSnapshot {
  job_id: string;
  status: JobStatus;
  phase: JobPhase;
  started_at: number;
  elapsed_s: number;
  tickers: string[];
  workflow: Workflow;
  ref_date: string;
  agents: Record<string, AgentResult[]>; // keyed by ticker
  cio: Record<string, CIOResult>;
  report: string;
  logs: string[];
  error: string | null;
  analysis_id: string | null;
}

export interface PortfolioPosition {
  ticker: string;
  quantity: number;
  avg_price: number;
}

export interface Portfolio {
  cash: number;
  positions: PortfolioPosition[];
}

export interface PortfolioValuePosition extends PortfolioPosition {
  current_price: number;
  market_value: number;
  pnl: number;
  pnl_pct: number;
}

export interface PortfolioValue {
  cash: number;
  positions: PortfolioValuePosition[];
  total_market_value: number;
  total_invested: number;
  total_pnl: number;
  total_pnl_pct: number;
}

export interface HistoryListItem {
  id: string;
  timestamp: string;
  tickers: string[];
  workflow: Workflow;
  summary: string;
}

export interface HistoryDetail {
  id: string;
  timestamp: string;
  tickers: string[];
  workflow: Workflow;
  summary: string;
  agents: Record<string, AgentResult[]>;
  cio: Record<string, CIOResult>;
  report: string;
}
