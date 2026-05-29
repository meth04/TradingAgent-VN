import { NextResponse } from "next/server";
import { loadDailyAnalysis, loadWorkflowTickerAnalysis } from "@/lib/data";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const date = searchParams.get("date");
  const ticker = searchParams.get("ticker");

  if (!date || !ticker) {
    return NextResponse.json({ error: "Missing date or ticker" }, { status: 400 });
  }

  const workflow = searchParams.get("workflow") || "cognitive";

  if (workflow !== "cognitive") {
    const analysis = loadWorkflowTickerAnalysis(date, ticker, workflow);
    if (analysis) {
      return NextResponse.json(analysis);
    }

    return NextResponse.json({
      _mock: true,
      workflow,
      ticker,
      date,
      message: "Không tìm thấy artifact phân tích có cấu trúc cho workflow/mã/ngày này.",
    });
  }

  const analysis = loadDailyAnalysis(date, ticker);
  return NextResponse.json(
    analysis || { _mock: true, workflow: "cognitive", ticker, date, message: "Không tìm thấy dữ liệu Cognitive phù hợp." }
  );
}
