import { NextResponse } from "next/server";
import Database from "better-sqlite3";
import path from "path";

const DB_PATH = path.join(process.cwd(), "../data/vnstock.db");

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const startDate = searchParams.get("start");
  const endDate = searchParams.get("end");

  if (!startDate || !endDate) {
    return NextResponse.json({ error: "Start and end dates are required" }, { status: 400 });
  }

  try {
    const db = new Database(DB_PATH, { readonly: true });

    // Try VN30 first, fallback to VNINDEX if not enough data
    const tryFetchBenchmark = (ticker: string) => {
      const query = `
        SELECT date, close
        FROM market_data_daily
        WHERE ticker = ?
        AND date >= ?
        AND date <= ?
        ORDER BY date ASC
      `;

      const stmt = db.prepare(query);
      const rows = stmt.all(ticker, startDate, endDate);
      
      return rows.map((row: any) => ({
        date: row.date.split(' ')[0], // Extract date part only (YYYY-MM-DD)
        value: row.close * 1000, // Convert to VND
      }));
    };

    let benchmarkData = tryFetchBenchmark('VN30');
    let benchmarkName = 'VN30';
    
    // If VN30 has less than 5 data points, try VNINDEX
    if (benchmarkData.length < 5) {
      console.log('VN30 data insufficient, trying VNINDEX');
      benchmarkData = tryFetchBenchmark('VNINDEX');
      benchmarkName = 'VNINDEX';
    }

    db.close();

    // Normalize to percentage returns (base 100)
    const normalizeData = (data: Array<{ date: string; value: number }>) => {
      if (data.length === 0) return [];
      const baseValue = data[0].value;
      return data.map((point) => ({
        date: point.date,
        value: (point.value / baseValue) * 100,
      }));
    };

    const normalized = normalizeData(benchmarkData);

    console.log(`Benchmark ${benchmarkName}: ${normalized.length} points, range: ${normalized[0]?.value.toFixed(2)}% to ${normalized[normalized.length - 1]?.value.toFixed(2)}%`);

    return NextResponse.json({
      benchmark: normalized,
      benchmarkName: benchmarkName,
    });
  } catch (error) {
    console.error("Error fetching benchmark data:", error);
    return NextResponse.json({ error: "Failed to fetch benchmark data" }, { status: 500 });
  }
}
