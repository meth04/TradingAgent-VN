import Database from "better-sqlite3";
import path from "path";
import { NextResponse } from "next/server";

const DB_PATH = path.join(process.cwd(), "../data/vnstock.db");
const ALLOWED_TICKERS = ["FPT", "HPG", "VCB", "SSI", "GAS"];

export async function GET() {
  const db = new Database(DB_PATH, { readonly: true });
  const rows = db.prepare(`SELECT DISTINCT ticker FROM market_data_daily ORDER BY ticker`).all() as { ticker: string }[];
  const available = new Set(rows.map((r) => r.ticker));
  const tickers = ALLOWED_TICKERS.filter((ticker) => available.has(ticker));
  return NextResponse.json(tickers);
}
