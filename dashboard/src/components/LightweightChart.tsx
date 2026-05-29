"use client";

import { useRef, useEffect } from "react";
import { Candle, Marker } from "./CandlestickChart";

// Workflow codes displayed on markers: 0=Traditional, 1=Kelly, 2=Markowitz, 3=Cognitive

const R = {
  bg: "#FFFFFF",
  grid: "#F5F5F5",
  text: "#333333",
  candleUp: "#10A37F",
  candleDown: "#EF4444",
  volUp: "rgba(16, 163, 127, 0.20)",
  volDown: "rgba(239, 68, 68, 0.20)",
  ma20: "#1890FF",
  ma50: "#FAAD14",
  bolinger: "#4285F4",
  rsi: "#666666",
  macdFast: "#1890FF",
  macdSlow: "#FAAD14",
  macdHistPos: "rgba(24, 144, 255, 0.35)",
  macdHistNeg: "rgba(250, 173, 20, 0.35)",
  border: "#000000",
  label: "#666666",
  paneBg: "#FFFFFF",
};

export default function LightweightChart({ candles, markers, visibleDays }: {
  candles: Candle[]; markers: Marker[]; visibleDays?: number | null;
}) {
  const mainRef = useRef<HTMLDivElement | null>(null);
  const rsiRef = useRef<HTMLDivElement | null>(null);
  const macdRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !mainRef.current || !candles.length) return;
    let main: any, rsiChart: any, macdChart: any, mounted = true;
    let overlay: HTMLCanvasElement | null = null;
    let candleSeries: any = null;
    let rafId: number;

    (async () => {
      const lwc = await import("lightweight-charts");
      const { createChart, CandlestickSeries, LineSeries, HistogramSeries, ColorType } = lwc;

      if (!mounted || !mainRef.current) return;

      const baseConf = (width: number, height: number, showTime = true) => ({
        width,
        height,
        layout: { background: { type: ColorType.Solid, color: R.bg }, textColor: R.text, fontFamily: "var(--font-jetbrains)" },
        grid: { vertLines: { color: R.grid }, horzLines: { color: R.grid } },
        timeScale: { timeVisible: true, borderVisible: false, rightOffset: 5, visible: showTime },
        rightPriceScale: { borderVisible: true, borderColor: R.border, autoScale: true, scaleMargins: { top: 0.08, bottom: 0.15 } },
        crosshair: { mode: 1 },
      });

      main = createChart(mainRef.current, baseConf(mainRef.current!.clientWidth || 1000, 370, true));

      candleSeries = main.addSeries(CandlestickSeries, {
        upColor: R.candleUp, downColor: R.candleDown,
        wickUpColor: R.candleUp, wickDownColor: R.candleDown,
        borderVisible: false, priceLineVisible: false, lastValueVisible: false,
        priceFormat: { type: "price", precision: 0, minMove: 1 },
      });
      candleSeries.setData(candles);

      const vol = main.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" }, priceLineVisible: false, lastValueVisible: false,
        priceScaleId: "vol",
      });
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
      vol.setData(candles.map((c: any) => ({
        time: c.time, value: c.volume,
        color: c.close >= c.open ? R.volUp : R.volDown,
      })));

      const calcMA = (period: number) => {
        const d: any[] = [];
        for (let i = period - 1; i < candles.length; i++) {
          const sl = candles.slice(i + 1 - period, i + 1);
          d.push({ time: candles[i].time, value: sl.reduce((a, b) => a + b.close, 0) / period });
        }
        return d;
      };
      const ma20Data = calcMA(20);
      const ma50Data = calcMA(50);

      if (ma20Data.length) main.addSeries(LineSeries, { color: R.ma20, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }).setData(ma20Data);
      if (ma50Data.length) main.addSeries(LineSeries, { color: R.ma50, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }).setData(ma50Data);

      if (ma20Data.length) {
        const upper: any[] = [];
        const lower: any[] = [];
        for (let i = 19; i < candles.length; i++) {
          const sl = candles.slice(i - 19, i + 1);
          const mean = sl.reduce((a, b) => a + b.close, 0) / 20;
          const variance = sl.reduce((a, b) => a + Math.pow(b.close - mean, 2), 0) / 20;
          const std = Math.sqrt(variance);
          upper.push({ time: candles[i].time, value: mean + 2 * std });
          lower.push({ time: candles[i].time, value: mean - 2 * std });
        }
        main.addSeries(LineSeries, { color: R.bolinger, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }).setData(upper);
        main.addSeries(LineSeries, { color: R.bolinger, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false }).setData(lower);
      }

      const syncRsiSize = () => {
        if (!rsiChart || !rsiRef.current) return;
        const width = Math.max(rsiRef.current.clientWidth, 1);
        const height = Math.max(rsiRef.current.clientHeight, 140);
        rsiChart.resize(width, height);
        rsiChart.priceScale("right").applyOptions({
          borderVisible: true,
          borderColor: R.border,
          scaleMargins: { top: 0.1, bottom: 0.1 },
          minimumWidth: 64,
        });
      };

      const hasInd = candles.length > 15;
      if (hasInd && rsiRef.current) {
        const rsiWidth = Math.max(rsiRef.current.clientWidth, 1);
        const rsiHeight = Math.max(rsiRef.current.clientHeight, 140);
        rsiChart = createChart(rsiRef.current, {
          width: rsiWidth,
          height: rsiHeight,
          layout: { background: { type: ColorType.Solid, color: R.bg }, textColor: R.text, fontFamily: "var(--font-jetbrains)" },
          grid: { vertLines: { color: R.grid }, horzLines: { color: R.grid } },
          timeScale: { timeVisible: true, borderVisible: false, rightOffset: 5, visible: false },
          rightPriceScale: { borderVisible: true, borderColor: R.border, autoScale: true, scaleMargins: { top: 0.1, bottom: 0.1 }, minimumWidth: 64 },
          crosshair: { mode: 1 },
        });
        const rsiData: any[] = [];
        let avgG = 0, avgL = 0;
        for (let i = 0; i < candles.length; i++) {
          if (i === 0) {
            rsiData.push({ time: candles[i].time, value: 50 });
            continue;
          }
          const d = candles[i].close - candles[i - 1].close;
          if (i <= 14) {
            if (d >= 0) avgG += d; else avgL -= d;
            if (i === 14) {
              avgG /= 14; avgL /= 14;
              const rsi = 100 - 100 / (1 + (avgL === 0 ? 100 : avgG / avgL));
              rsiData.push({ time: candles[i].time, value: rsi });
            } else {
              rsiData.push({ time: candles[i].time, value: 50 });
            }
          } else {
            avgG = (avgG * 13 + (d > 0 ? d : 0)) / 14;
            avgL = (avgL * 13 + (d < 0 ? -d : 0)) / 14;
            const rsi = 100 - 100 / (1 + (avgL === 0 ? 100 : avgG / avgL));
            rsiData.push({ time: candles[i].time, value: rsi });
          }
        }
        rsiChart.addSeries(LineSeries, { color: R.rsi, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false }).setData(rsiData);
        syncRsiSize();
        if (rsiData.length > 1) {
          const ts = rsiData.map((d: any) => d.time);
          rsiChart.addSeries(LineSeries, { color: R.border, lineWidth: 0.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false })
            .setData(ts.map((t: string) => ({ time: t, value: 70 })));
          rsiChart.addSeries(LineSeries, { color: R.border, lineWidth: 0.5, lineStyle: 2, priceLineVisible: false, lastValueVisible: false })
            .setData(ts.map((t: string) => ({ time: t, value: 30 })));
        }
      }

      if (hasInd && macdRef.current && candles.length > 26) {
        macdChart = createChart(macdRef.current, baseConf(macdRef.current.clientWidth || 1000, 140, false));
        const ema = (p: number) => {
          const k = 2 / (p + 1); const r: number[] = []; let prev = candles[0]?.close ?? 0;
          candles.forEach(c => { const v = c.close * k + prev * (1 - k); r.push(v); prev = v; });
          return r;
        };
        const e12 = ema(12), e26 = ema(26);
        const macdLine = e12.map((v, i) => v - (e26[i] || 0));
        const signal: number[] = []; let ps = macdLine[0] ?? 0;
        macdLine.forEach(v => { const val = v * 0.2 + ps * 0.8; signal.push(val); ps = val; });

        macdChart.addSeries(LineSeries, { color: R.macdFast, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false })
          .setData(macdLine.map((v, i) => ({ time: candles[i].time, value: v })));
        macdChart.addSeries(LineSeries, { color: R.macdSlow, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false })
          .setData(signal.map((v, i) => ({ time: candles[i].time, value: v })));
        macdChart.addSeries(HistogramSeries, { base: 0, priceLineVisible: false, lastValueVisible: false })
          .setData(macdLine.map((v, i) => ({
            time: candles[i].time, value: v - signal[i],
            color: v - signal[i] >= 0 ? R.macdHistPos : R.macdHistNeg,
          })));
      }

      overlay = document.createElement("canvas");
      overlay.style.cssText = "position:absolute;top:0;left:0;pointer-events:none;z-index:20;";
      mainRef.current.appendChild(overlay);

      const dpi = window.devicePixelRatio || 1;
      const renderOverlay = () => {
        if (!overlay || !mainRef.current || !candleSeries) return;
        const rect = mainRef.current.getBoundingClientRect();
        overlay.width = Math.floor(rect.width * dpi);
        overlay.height = Math.floor(rect.height * dpi);
        overlay.style.width = `${rect.width}px`;
        overlay.style.height = `${rect.height}px`;
        const ctx = overlay.getContext("2d");
        if (!ctx) return;
        ctx.clearRect(0, 0, overlay.width, overlay.height);
        ctx.save();
        ctx.scale(dpi, dpi);

        const groups: Record<string, typeof markers> = {};
        markers.forEach(m => {
          const key = `${m.time}-${m.position}`;
          if (!groups[key]) groups[key] = [];
          groups[key].push(m);
        });

        Object.values(groups).forEach(group => {
          group.sort((a, b) => {
            const amtA = a.investedAmount || 0;
            const amtB = b.investedAmount || 0;
            if (Math.abs(amtB - amtA) > 0.01) return amtB - amtA;
            const wfA = a.workflow || "";
            const wfB = b.workflow || "";
            return wfA.localeCompare(wfB);
          });

          group.forEach((m, idx) => {
            const candle = candles.find(c => c.time === m.time);
            if (!candle) return;
            const price = m.position === "aboveBar" ? candle.high : candle.low;
            const yCoord = candleSeries.priceToCoordinate(price);
            const xCoord = main.timeScale().timeToCoordinate(m.time as any);
            if (yCoord === null || xCoord === null) return;

            const baseOffset = m.position === "aboveBar" ? -20 : 20;
            const step = m.position === "aboveBar" ? -22 : 22;
            const y = yCoord + baseOffset + (idx * step);
            const rad = 10;

            ctx.save();
            ctx.shadowColor = "rgba(0,0,0,0.12)";
            ctx.shadowBlur = 3;
            ctx.shadowOffsetY = 1;
            ctx.fillStyle = m.color;
            ctx.beginPath(); ctx.arc(xCoord, y, rad, 0, Math.PI * 2); ctx.fill();
            ctx.restore();

            ctx.strokeStyle = "rgba(0,0,0,0.2)";
            ctx.lineWidth = 1.2;
            ctx.beginPath(); ctx.arc(xCoord, y, rad, 0, Math.PI * 2); ctx.stroke();

            ctx.font = "900 14px var(--font-vt323), var(--font-jetbrains), monospace";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillStyle = "#FFFFFF";
            ctx.fillText(m.text, xCoord, y + 1);
          });
        });
        ctx.restore();
      };

      let lastCoordsStr = "";

      const renderLoop = () => {
        if (!mounted || !main) return;
        let newCoordsStr = `${main.timeScale().getVisibleRange()?.from}-${main.timeScale().getVisibleRange()?.to}`;
        if (candles.length > 0 && candleSeries) {
           const y = candleSeries.priceToCoordinate(candles[0].high);
           newCoordsStr += `-${y}`;
        }
        if (newCoordsStr !== lastCoordsStr) {
           lastCoordsStr = newCoordsStr;
           renderOverlay();
        }
        rafId = requestAnimationFrame(renderLoop);
      };
      renderLoop();

      main.timeScale().subscribeVisibleLogicalRangeChange((e: any) => {
        if (visibleDays && e && candles.length) {
          const to = typeof e.to === "number" ? Math.floor(e.to) : candles.length - 1;
          const from = Math.max(0, to - visibleDays + 1);
          main.timeScale().setVisibleLogicalRange({ from, to });
          if (rsiChart) rsiChart.timeScale().setVisibleLogicalRange({ from, to });
          if (macdChart) macdChart.timeScale().setVisibleLogicalRange({ from, to });
        }
      });

      const syncRange = (range: any) => {
        if (!range) return;
        rsiChart?.timeScale().setVisibleLogicalRange(range);
        macdChart?.timeScale().setVisibleLogicalRange(range);
      };
      main.timeScale().subscribeVisibleLogicalRangeChange(syncRange);

      const fitInitial = () => {
        const total = candles.length;
        const to = total - 1;
        const from = visibleDays ? Math.max(0, total - visibleDays) : 0;
        main.timeScale().setVisibleLogicalRange({ from, to });
        if (rsiChart && rsiRef.current) {
          syncRsiSize();
          rsiChart.timeScale().setVisibleLogicalRange({ from, to });
        }
        if (macdChart && macdRef.current) {
          macdChart.resize(
            macdRef.current.clientWidth || 1000,
            macdRef.current.clientHeight || 140,
          );
          macdChart.timeScale().setVisibleLogicalRange({ from, to });
        }
      };
      fitInitial();
      setTimeout(fitInitial, 20);

      const onResize = () => {
        const mainWidth = mainRef.current?.clientWidth || 1000;
        const macdWidth = macdRef.current?.clientWidth || mainWidth;
        main.resize(mainWidth, 370);
        syncRsiSize();
        macdChart?.resize(macdWidth, macdRef.current?.clientHeight || 140);
        renderOverlay();
      };
      window.addEventListener("resize", onResize);

      return () => {
        window.removeEventListener("resize", onResize);
      };
    })();

    return () => {
      mounted = false;
      if (rafId) cancelAnimationFrame(rafId);
      main?.remove?.();
      rsiChart?.remove?.();
      macdChart?.remove?.();
      overlay?.remove?.();
    };
  }, [candles, markers, visibleDays]);

  return (
    <div className="w-full">
      <div ref={mainRef} className="w-full relative" />
      <div className="mt-6 grid gap-4">
        <div className="border border-black bg-white px-4 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[#666666]">
          RSI (14)
        </div>
        <div ref={rsiRef} className="w-full h-[140px] min-h-[140px] overflow-visible" />
        <div className="border border-black bg-white px-4 py-2 font-mono text-[10px] uppercase tracking-[0.16em] text-[#666666]">
          MACD (12, 26, 9)
        </div>
        <div ref={macdRef} className="w-full h-[140px] min-h-[140px]" />
      </div>
    </div>
  );
}
