import Database from 'better-sqlite3';
import path from 'path';
import { NextRequest, NextResponse } from 'next/server';

const DB_PATH = path.join(process.cwd(), "../data/vnstock.db");

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const ticker = searchParams.get('ticker');
  const start = searchParams.get('start');
  const end = searchParams.get('end');

  if (!ticker) {
    return NextResponse.json({ error: 'ticker is required' }, { status: 400 });
  }

  try {
    const db = new Database(DB_PATH, { readonly: true });
    const rows = db
      .prepare(
        `WITH ranked AS (
           SELECT *,
                  ROW_NUMBER() OVER (PARTITION BY substr(date,1,10) ORDER BY date ASC) as rn_first,
                  ROW_NUMBER() OVER (PARTITION BY substr(date,1,10) ORDER BY date DESC) as rn_last
           FROM market_data_daily
           WHERE ticker = @ticker
           ${start ? "AND substr(date,1,10) >= @start" : ""}
           ${end ? "AND substr(date,1,10) <= @end" : ""}
         )
         SELECT 
            substr(date,1,10) as time,
            MAX(CASE WHEN rn_first = 1 THEN open END) as open,
            MAX(high) as high,
            MIN(low) as low,
            MAX(CASE WHEN rn_last = 1 THEN close END) as close,
            SUM(volume) as volume
         FROM ranked
         GROUP BY substr(date,1,10)
         ORDER BY time ASC`
      )
      .all({ ticker, start, end }) as any[];

    // Manual deduplicate to ensure unique times for lightweight-charts
    const uniqueRows: any[] = [];
    const seenTimes = new Set<string>();
    for (const row of rows) {
      if (!seenTimes.has(row.time)) {
        uniqueRows.push(row);
        seenTimes.add(row.time);
      }
    }

    return NextResponse.json(uniqueRows);
  } catch (err: any) {
    console.error("API Error:", err);
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
