"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { VT323 } from "next/font/google";
import { usePlayback } from "@/contexts/PlaybackContext";
import { formatDate } from "@/lib/format";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const PLAYBACK_ENABLED_ROUTES = new Set(["/leaderboard", "/trading-view"]);

export function PlaybackSlider() {
  const pathname = usePathname();
  const { dates, currentDate, setCurrentDate } = usePlayback();

  useEffect(() => {
    if (dates.length && !currentDate && PLAYBACK_ENABLED_ROUTES.has(pathname)) {
      setCurrentDate(dates[dates.length - 1]);
    }
  }, [dates, currentDate, setCurrentDate, pathname]);

  if (!PLAYBACK_ENABLED_ROUTES.has(pathname)) {
    return null;
  }

  const currentIndex = currentDate ? dates.indexOf(currentDate) : dates.length - 1;

  return (
    <footer className="footer w-full border-t-2 border-border bg-[#F5F5F5] px-5 py-4 md:px-8">
      <div className="mx-auto flex w-full max-w-[1560px] flex-col gap-3 md:flex-row md:items-center md:gap-6">
        <div className="min-w-[220px]">
          <div className="text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">Mốc thời gian phát lại</div>
          <div className={`${vt323.className} text-2xl uppercase tracking-[0.16em] text-[#000000]`}>
            {currentDate ? formatDate(currentDate) : "Chọn ngày"}
          </div>
        </div>

        <div className="flex-1">
          <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
            <span>Diễn tiến backtest</span>
            <span>{dates.length ? `${Math.max(currentIndex + 1, 1)} / ${dates.length}` : "0 / 0"}</span>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(dates.length - 1, 0)}
            value={currentIndex >= 0 ? currentIndex : 0}
            onChange={(e) => {
              const idx = Number(e.target.value);
              const next = dates[idx];
              if (next) setCurrentDate(next);
            }}
            className="playback-range w-full appearance-none"
            style={{
              backgroundImage: `linear-gradient(to right, var(--accent-green) 0%, var(--accent-green) ${
                dates.length > 1 ? (currentIndex / (dates.length - 1)) * 100 : 0
              }%, var(--border-light) ${
                dates.length > 1 ? (currentIndex / (dates.length - 1)) * 100 : 0
              }%, var(--border-light) 100%)`,
            }}
          />
        </div>
      </div>
    </footer>
  );
}
