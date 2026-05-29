import type {
  JobSnapshot,
  Portfolio,
  PortfolioValue,
  HistoryListItem,
  HistoryDetail,
  Workflow,
} from "./types";

const API = ""; // proxied via next.config rewrites → http://localhost:8000

export async function getPortfolio(): Promise<Portfolio> {
  const res = await fetch(`${API}/api/portfolio`, { cache: "no-store" });
  if (!res.ok) throw new Error("Không tải được portfolio");
  return res.json();
}

export async function savePortfolio(p: Portfolio): Promise<Portfolio> {
  const res = await fetch(`${API}/api/portfolio`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(p),
  });
  if (!res.ok) throw new Error("Không lưu được portfolio");
  return res.json();
}

export async function getPortfolioValue(): Promise<PortfolioValue> {
  const res = await fetch(`${API}/api/portfolio/value`, { cache: "no-store" });
  if (!res.ok) throw new Error("Không tính được giá trị danh mục");
  return res.json();
}

export async function getMarketPrices(tickers: string[]): Promise<Record<string, number>> {
  const q = tickers.join(",");
  const res = await fetch(`${API}/api/market/prices?tickers=${encodeURIComponent(q)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error("Không lấy được giá");
  return res.json();
}

export async function listHistory(): Promise<HistoryListItem[]> {
  const res = await fetch(`${API}/api/history`, { cache: "no-store" });
  if (!res.ok) throw new Error("Không tải được lịch sử");
  return res.json();
}

export async function getHistoryDetail(id: string): Promise<HistoryDetail> {
  const res = await fetch(`${API}/api/history/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Không tải được chi tiết lịch sử");
  return res.json();
}

/** Kick off a new analysis job. Returns the job_id immediately. */
export async function createAnalysis(
  tickers: string[],
  workflow: Workflow,
  signal?: AbortSignal,
): Promise<{ job_id: string }> {
  const res = await fetch(`${API}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tickers, workflow }),
    signal,
  });
  if (!res.ok) {
    throw new Error(`Không tạo được phân tích (HTTP ${res.status})`);
  }
  return res.json();
}

/** Fetch the current snapshot for a job. Throws on 404 / network error. */
export async function getAnalysisJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<JobSnapshot> {
  const res = await fetch(`${API}/api/analyze/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    throw new Error(`Không tải được job (HTTP ${res.status})`);
  }
  return res.json();
}
