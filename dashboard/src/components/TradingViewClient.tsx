"use client";

import { useEffect, useMemo, useState } from "react";
import CandlestickChart from "@/components/CandlestickChart";
import { PlaybackInit } from "@/components/PlaybackInit";
import { LedgerEntry, PortfolioState } from "@/lib/data";
import { usePlayback } from "@/contexts/PlaybackContext";
import { formatDate, addDays } from "@/lib/format";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const TIMEFRAMES: Record<string, number | null> = {
  "5D": 5,
  "1M": 30,
  "3M": 90,
  "6M": 180,
  "1Y": 365,
  ALL: null,
};

async function fetchTickers() {
  const res = await fetch("/api/tickers");
  if (!res.ok) throw new Error("Failed to fetch tickers");
  return res.json();
}

async function fetchCandles(ticker: string, start?: string, end?: string) {
  const params = new URLSearchParams({ ticker });
  if (start) params.set("start", start);
  if (end) params.set("end", end);
  const res = await fetch(`/api/candles?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch candles");
  return res.json();
}

function mergeLedgersUpTo(
  ledgersAll: Record<string, Record<string, LedgerEntry[]>>,
  cutoff: string,
  ticker?: string
) {
  const acc: Record<string, LedgerEntry[]> = {};
  Object.entries(ledgersAll).forEach(([date, workflows]) => {
    if (date <= cutoff) {
      Object.entries(workflows).forEach(([wf, entries]) => {
        entries.forEach((e) => {
          if (!ticker || e.ticker === ticker) {
            acc[wf] = (acc[wf] || []).concat(e);
          }
        });
      });
    }
  });
  return acc;
}

export function TradingViewClient({
  states,
  playbackDates,
  ledgersAll,
  highlightWorkflow,
}: {
  states: Record<string, PortfolioState>;
  playbackDates: string[];
  ledgersAll: Record<string, Record<string, LedgerEntry[]>>;
  highlightWorkflow?: string;
}) {
  const { dates, setDates, currentDate, setCurrentDate } = usePlayback();
  const [tickers, setTickers] = useState<string[]>([]);
  const [ticker, setTicker] = useState<string>("");
  const [timeframe, setTimeframe] = useState<string>("1M");
  const [candles, setCandles] = useState<any[]>([]);
  const [showLegend, setShowLegend] = useState(true);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  useEffect(() => {
    if (!dates.length && playbackDates.length) {
      setDates(playbackDates);
      if (!currentDate) setCurrentDate(playbackDates[playbackDates.length - 1]);
    }
  }, [dates.length, playbackDates, setDates, currentDate, setCurrentDate]);

  useEffect(() => {
    fetchTickers().then((list) => {
      setTickers(list);
      if (!ticker && list.length) {
        setTicker(list.includes("TCB") ? "TCB" : list[0]);
      }
    });
  }, [ticker]);

  useEffect(() => {
    if (!ticker || !playbackDates.length) return;
    const end = currentDate || playbackDates[playbackDates.length - 1];
    const days = TIMEFRAMES[timeframe];
    const fetchDays = days ? days + 100 : undefined;
    const start = fetchDays ? addDays(end, -fetchDays) : undefined;

    fetchCandles(ticker, start, end).then((data) => {
      setCandles(data);
    });
  }, [ticker, timeframe, currentDate, playbackDates]);

  const ledgersForTicker = useMemo(() => {
    const cutoff = currentDate || playbackDates[playbackDates.length - 1] || "";
    return mergeLedgersUpTo(ledgersAll, cutoff, ticker);
  }, [ledgersAll, ticker, currentDate, playbackDates]);

  const playbackLabel = formatDate(currentDate || playbackDates[playbackDates.length - 1] || "");

  return (
    <div className="w-full px-4 py-14 md:px-8 md:py-16">
      <PlaybackInit dates={playbackDates} />
      <div className="mx-auto flex max-w-7xl flex-col gap-12">
        <section className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">
              Kiểm tra thực thi
            </div>
            <h1 className={`${vt323.className} text-6xl uppercase tracking-[0.08em] text-[#000000] md:text-7xl`}>
              Trading View
            </h1>
            <p className="max-w-3xl text-sm leading-8 text-[#666666] md:text-[15px]">
              Trang này nối hành động của Workflow với dữ liệu giá đã lưu. Mục tiêu là mọi người nhìn thấy cách một quyết định giao dịch xuất hiện trong bối cảnh thị trường tương ứng của từng mã cổ phiếu.
            </p>
          </div>
          <div className="pixel-border bg-[var(--surface-tint)] p-6 md:p-7">
            <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
              Mốc playback hiện tại
            </div>
            <div className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
              {playbackLabel}
            </div>
          </div>
        </section>

        <section className="pixel-border bg-[#FFFFFF] p-6 md:p-8">
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">Ticker</div>
              <div className="relative z-50 font-mono text-sm text-[#000000]">
                <button
                  className="min-w-[90px] border-2 border-border bg-[#FFFFFF] px-3 py-2 text-left shadow-[4px_4px_0_rgba(36,28,57,0.96)]"
                  onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span>{ticker || "---"}</span>
                    <span className="text-[10px] text-text-secondary">{isDropdownOpen ? "▲" : "▼"}</span>
                  </div>
                </button>
                {isDropdownOpen && (
                  <>
                    <div className="fixed inset-0 z-40" onClick={() => setIsDropdownOpen(false)} />
                    <div className="absolute top-full left-0 z-50 mt-1 max-h-60 w-[130px] overflow-y-auto border-2 border-border bg-[#FFFFFF] shadow-[4px_4px_0_rgba(36,28,57,0.96)]">
                      {tickers.map((t) => (
                        <div
                          key={t}
                          className={`cursor-pointer px-3 py-2 transition-colors ${
                            ticker === t ? "bg-[#F5F5F5] text-[#000000] font-bold" : "hover:bg-[#F9F9F9]"
                          }`}
                          onClick={() => {
                            setTicker(t);
                            setIsDropdownOpen(false);
                          }}
                        >
                          {t}
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>

              <div className="ml-2 text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">Khung thời gian</div>
              <div className="flex flex-wrap gap-2">
                {Object.keys(TIMEFRAMES).map((tf) => (
                  <button
                    key={tf}
                    className={`border px-3 py-2 text-[11px] uppercase tracking-[0.14em] font-mono transition-colors ${
                      tf === timeframe
                        ? "border-[#FF6B35] bg-[#FF6B35] text-white"
                        : "border-border bg-[#FFFFFF] text-[#000000] hover:border-[#FAAD14] hover:bg-[#F9F9F9]"
                    }`}
                    onClick={() => setTimeframe(tf)}
                  >
                    {tf}
                  </button>
                ))}
              </div>

              <div className="ml-auto text-[11px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                {highlightWorkflow ? `Workflow đang nhấn mạnh: ${highlightWorkflow}` : "Marker khả dụng"}
              </div>

              <button
                onClick={() => setShowLegend(!showLegend)}
                className={`border px-3 py-2 text-[11px] uppercase tracking-[0.14em] font-mono transition-colors ${
                  showLegend
                    ? "border-[#FAAD14] bg-[#FAAD14] text-[#000000]"
                    : "border-border bg-[#FFFFFF] text-[#000000]"
                }`}
                title="Ẩn hoặc hiện legend"
              >
                Legend
              </button>
            </div>

            {showLegend ? (
              <div className="border border-border-light bg-[var(--surface-warm)] px-4 py-4 text-[11px] text-[#666666] font-mono">
                <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-text-secondary">Legend tín hiệu</div>
                <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                  <span>0 = Traditional</span>
                  <span>1 = Kelly</span>
                  <span>2 = Markowitz</span>
                  <span>3 = Cognitive</span>
                  <span className="text-[#999999]">│</span>
                  <span className="flex items-center gap-2"><span className="h-3 w-3 border border-border bg-[#FAAD14]" /> Mua / Buy more</span>
                  <span className="flex items-center gap-2"><span className="h-3 w-3 border border-border bg-[#10A37F]" /> Bán có lãi</span>
                  <span className="flex items-center gap-2"><span className="h-3 w-3 border border-border bg-[#EF4444]" /> Bán thua lỗ</span>
                </div>
              </div>
            ) : null}
          </div>
        </section>

        <section className="pixel-border bg-[#FFFFFF] p-4 md:p-6">
          <CandlestickChart
            ticker={ticker || "--"}
            candles={candles}
            ledgers={ledgersForTicker}
            playbackDate={currentDate || playbackDates[playbackDates.length - 1]}
            visibleDays={TIMEFRAMES[timeframe]}
          />
        </section>
      </div>
    </div>
  );
}
