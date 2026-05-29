"use client";

import { useEffect, useState } from "react";
import { VT323 } from "next/font/google";
import { getMarketPrices } from "@/lib/api";
import { formatVnd } from "@/lib/format";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface Props {
  tickers: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}

const PRICE_REFRESH_MS = 30_000;

export function TickerSelector({ tickers, selected, onChange }: Props) {
  const [prices, setPrices] = useState<Record<string, number>>({});

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setInterval> | null = null;

    const refresh = () => {
      getMarketPrices(tickers)
        .then((p) => alive && setPrices(p))
        .catch(() => {});
    };

    refresh(); // fetch once immediately, then every 30s
    timer = setInterval(refresh, PRICE_REFRESH_MS);

    return () => {
      alive = false;
      if (timer) clearInterval(timer);
    };
  }, [tickers]);

  function toggle(t: string) {
    if (selected.includes(t)) onChange(selected.filter((x) => x !== t));
    else onChange([...selected, t]);
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="tagline">Bước 01</span>
          <h3
            className={`${vt323.className} text-xl uppercase tracking-[0.06em] text-black leading-none`}
          >
            Mã cổ phiếu
          </h3>
        </div>
        <span className="badge badge-info">{selected.length}</span>
      </div>

      <div className="flex flex-col gap-1.5">
        {tickers.map((t) => {
          const on = selected.includes(t);
          const price = prices[t];
          return (
            <button
              key={t}
              type="button"
              onClick={() => toggle(t)}
              className={`flex items-center gap-3 px-3 py-2 border-2 transition-all text-left ${
                on
                  ? "border-black bg-[#FAAD14] shadow-[2px_2px_0_#000000]"
                  : "border-black bg-white hover:bg-[#FFF6E0] shadow-[1px_1px_0_#000000]"
              }`}
            >
              <span
                className={`w-4 h-4 border-2 border-black flex items-center justify-center text-[10px] font-bold leading-none ${
                  on ? "bg-black text-[#FAAD14]" : "bg-white"
                }`}
              >
                {on ? "✓" : ""}
              </span>
              <span
                className={`${vt323.className} text-lg tracking-widest font-bold leading-none text-black flex-1`}
              >
                {t}
              </span>
              <span
                className={`text-[10px] font-mono ${
                  on ? "text-black/70" : "text-[#555555]"
                }`}
              >
                {price ? `${formatVnd(price)}đ` : "—"}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
