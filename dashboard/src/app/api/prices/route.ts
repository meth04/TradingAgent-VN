import { NextResponse } from "next/server";
import Database from "better-sqlite3";
import path from "path";

const DB_PATH = path.join(process.cwd(), "../data/vnstock.db");

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const tickers = searchParams.get("tickers")?.split(",") || [];

  if (tickers.length === 0) {
    return NextResponse.json({ error: "No tickers provided" }, { status: 400 });
  }

  try {
    const db = new Database(DB_PATH, { readonly: true });

    const placeholders = tickers.map(() => "?").join(",");
    const query = `
      SELECT ticker, close, date
      FROM market_data_daily
      WHERE ticker IN (${placeholders})
      AND date = (
        SELECT MAX(date)
        FROM market_data_daily md2
        WHERE md2.ticker = market_data_daily.ticker
      )
    `;

    const stmt = db.prepare(query);
    const rows = stmt.all(...tickers);
    
    const prices: Record<string, number> = {};
    rows.forEach((row: any) => {
      // Prices in database are in thousands (VND), multiply by 1000
      prices[row.ticker] = row.close * 1000;
    });

    db.close();

    return NextResponse.json(prices);
  } catch (error) {
    console.error("Error fetching prices:", error);
    return NextResponse.json({ error: "Failed to fetch prices" }, { status: 500 });
  }
}
