"use client";

import { ColorType, LineStyle, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { Candle, Marker } from "./CandlestickChart";

function computeMA(data: Candle[], period: number) {
  const result: { time: Time; value: number }[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i + 1 < period) continue;
    const slice = data.slice(i + 1 - period, i + 1);
    const avg = slice.reduce((s, c) => s + c.close, 0) / period;
    result.push({ time: data[i].time as unknown as Time, value: avg });
  }
  return result;
}

function computeBollinger(data: Candle[], period = 20, mult = 2) {
  const upper: { time: Time; value: number }[] = [];
  const basis: { time: Time; value: number }[] = [];
  const lower: { time: Time; value: number }[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i + 1 < period) continue;
    const slice = data.slice(i + 1 - period, i + 1);
    const mean = slice.reduce((s, c) => s + c.close, 0) / period;
    const variance = slice.reduce((s, c) => s + Math.pow(c.close - mean, 2), 0) / period;
    const std = Math.sqrt(variance);
    const t = data[i].time as unknown as Time;
    basis.push({ time: t, value: mean });
    upper.push({ time: t, value: mean + mult * std });
    lower.push({ time: t, value: mean - mult * std });
  }
  return { upper, basis, lower };
}

function computeRSI(data: Candle[], period = 14) {
  const result: { time: Time; value: number }[] = [];
  let gain = 0;
  let loss = 0;
  for (let i = 1; i < data.length; i++) {
    const diff = data[i].close - data[i - 1].close;
    if (i <= period) {
      if (diff >= 0) gain += diff; else loss -= diff;
      if (i === period) {
        const avgGain = gain / period;
        const avgLoss = loss / period;
        const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
        const rsi = 100 - 100 / (1 + rs);
        result.push({ time: data[i].time as unknown as Time, value: rsi });
      }
    } else {
      const g = diff > 0 ? diff : 0;
      const l = diff < 0 ? -diff : 0;
      gain = (gain * (period - 1) + g) / period;
      loss = (loss * (period - 1) + l) / period;
      const rs = loss === 0 ? 100 : gain / loss;
      const rsi = 100 - 100 / (1 + rs);
      result.push({ time: data[i].time as unknown as Time, value: rsi });
    }
  }
  return result;
}

function computeMACD(data: Candle[], fast = 12, slow = 26, signal = 9) {
  const ema = (period: number) => {
    const k = 2 / (period + 1);
    const res: number[] = [];
    let prev = data[0]?.close ?? 0;
    for (let i = 0; i < data.length; i++) {
      const val = data[i].close * k + prev * (1 - k);
      res.push(val);
      prev = val;
    }
    return res;
  };
  const emaFast = ema(fast);
  const emaSlow = ema(slow);
  const macd: number[] = emaFast.map((v, i) => v - emaSlow[i]);
  const signalLine: number[] = [];
  const kSig = 2 / (signal + 1);
  let prevSig = macd[0] ?? 0;
  macd.forEach((v) => {
    const s = v * kSig + prevSig * (1 - kSig);
    signalLine.push(s);
    prevSig = s;
  });
  const histogram = macd.map((v, i) => v - signalLine[i]);
  const times = data.map((d) => d.time as unknown as Time);
  return {
    macd: macd.map((v, i) => ({ time: times[i], value: v })),
    signal: signalLine.map((v, i) => ({ time: times[i], value: v })),
    hist: histogram.map((v, i) => ({ time: times[i], value: v })),
  };
}

export default function LightweightChart({ candles, markers }: { candles: Candle[]; markers: Marker[] }) {
  const mainRef = useRef<HTMLDivElement | null>(null);
  const rsiRef = useRef<HTMLDivElement | null>(null);
  const macdRef = useRef<HTMLDivElement | null>(null);

  const hasRsi = candles.length > 14;
  const hasMacd = candles.length > 26;

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!mainRef.current || !candles.length) return;

    let mainChart: any = null;
    let rsiChart: any = null;
    let macdChart: any = null;
    let isMounted = true;

    const init = async () => {
      const lwc = await import("lightweight-charts");
      const { createChart, CandlestickSeries, LineSeries, HistogramSeries, ColorType, LineStyle, createSeriesMarkers } = lwc as any;
      if (!isMounted || !mainRef.current) return;

      const bg = "#FFFFFF";
      const commonLayout = {
        layout: {
          background: { type: ColorType.Solid, color: bg },
          textColor: "#333333",
          fontFamily: "var(--font-jetbrains)",
        },
        grid: {
          vertLines: { color: "#F5F5F5" },
          horzLines: { color: "#F5F5F5" },
        },
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          borderVisible: false,
          rightOffset: 5,
          barSpacing: candles.length < 50 ? 15 : 6,
        },
        rightPriceScale: { borderVisible: false, autoScale: true },
      };

      mainChart = createChart(mainRef.current, {
        width: mainRef.current.clientWidth || 800,
        height: hasRsi || hasMacd ? 400 : 550,
        ...commonLayout,
      });

      const candleSeries = mainChart.addSeries(CandlestickSeries, {
        upColor: "#10A37F",
        downColor: "#EF4444",
        wickUpColor: "#10A37F",
        wickDownColor: "#EF4444",
        borderVisible: false,
      });

      candleSeries.setData(
        candles.map((c) => ({
          time: c.time as any,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );

      const ma20 = computeMA(candles, 20);
      const ma50 = computeMA(candles, 50);
      if (ma20.length) mainChart.addSeries(LineSeries, { color: "#1890FF", lineWidth: 2, priceLineVisible: false }).setData(ma20);
      if (ma50.length) mainChart.addSeries(LineSeries, { color: "#FAAD14", lineWidth: 2, priceLineVisible: false }).setData(ma50);

      const bb = computeBollinger(candles, 20, 2);
      if (bb.upper.length) {
        mainChart.addSeries(LineSeries, { color: "#666666", lineWidth: 1, lineStyle: LineStyle.Solid, priceLineVisible: false }).setData(bb.upper);
        mainChart.addSeries(LineSeries, { color: "#999999", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false }).setData(bb.basis);
        mainChart.addSeries(LineSeries, { color: "#666666", lineWidth: 1, lineStyle: LineStyle.Solid, priceLineVisible: false }).setData(bb.lower);
      }

      const formattedMarkers = markers.map((m) => ({
        time: m.time as any,
        position: m.position,
        color: m.color,
        shape: "circle" as any,
        text: m.text,
        id: m.id,
      }));

      setTimeout(() => {
        if (!isMounted || !mainChart || !candleSeries) return;
        try {
          if (typeof createSeriesMarkers === "function") {
             createSeriesMarkers(candleSeries, formattedMarkers);
          } else if (typeof candleSeries.setMarkers === "function") {
             candleSeries.setMarkers(formattedMarkers);
          }
        } catch (e) {
          console.warn("Could not set markers:", e);
        }
        mainChart.timeScale().fitContent();
      }, 50);

      if (hasRsi && rsiRef.current) {
        rsiChart = createChart(rsiRef.current, {
          width: rsiRef.current.clientWidth || 800,
          height: 140,
          ...commonLayout,
        });
        rsiChart.priceScale("right").applyOptions({ borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } });
        rsiChart.timeScale().applyOptions({ borderVisible: false });
        const rsiSeries = rsiChart.addSeries(LineSeries, { color: "#666666", lineWidth: 1, priceLineVisible: false });
        const rsiData = computeRSI(candles);
        if (rsiData.length) rsiSeries.setData(rsiData);
        rsiChart.addSeries(LineSeries, { color: "#EF4444", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false }).setData([
          { time: candles[0].time as any, value: 70 },
          { time: candles[candles.length - 1].time as any, value: 70 },
        ]);
        rsiChart.addSeries(LineSeries, { color: "#10A37F", lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false }).setData([
          { time: candles[0].time as any, value: 30 },
          { time: candles[candles.length - 1].time as any, value: 30 },
        ]);
      }

      if (hasMacd && macdRef.current) {
        macdChart = createChart(macdRef.current, {
          width: macdRef.current.clientWidth || 800,
          height: 160,
          ...commonLayout,
        });
        macdChart.priceScale("right").applyOptions({ borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } });
        macdChart.timeScale().applyOptions({ borderVisible: false });
        const macdData = computeMACD(candles);
        if (macdData.macd.length) {
          macdChart.addSeries(LineSeries, { color: "#10A37F", lineWidth: 1, priceLineVisible: false }).setData(macdData.macd);
          macdChart.addSeries(LineSeries, { color: "#EF4444", lineWidth: 1, priceLineVisible: false }).setData(macdData.signal);

          const histSeries = macdChart.addSeries(HistogramSeries, { base: 0, lineWidth: 1, priceLineVisible: false });
          histSeries.setData(
            macdData.hist.map((h) => ({
              time: h.time,
              value: h.value,
              color: h.value >= 0 ? "#1890FF" : "#EF4444",
            }))
          );
        }
      }

      setTimeout(() => {
        if (isMounted) {
          mainChart?.timeScale().fitContent();
          rsiChart?.timeScale().fitContent();
          macdChart?.timeScale().fitContent();
        }
      }, 150);
    };

    init();

    const handleResize = () => {
      if (mainChart && mainRef.current) mainChart.applyOptions({ width: mainRef.current.clientWidth });
      if (rsiChart && rsiRef.current) rsiChart.applyOptions({ width: rsiRef.current.clientWidth });
      if (macdChart && macdRef.current) macdChart.applyOptions({ width: macdRef.current.clientWidth });
    };

    window.addEventListener("resize", handleResize);
    return () => {
      isMounted = false;
      window.removeEventListener("resize", handleResize);
      mainChart?.remove?.();
      rsiChart?.remove?.();
      macdChart?.remove?.();
    };
  }, [candles, markers, hasRsi, hasMacd]);

  return (
    <div className="space-y-4">
      <div ref={mainRef} className="w-full" />
      {hasRsi && <div ref={rsiRef} className="w-full" />}
      {hasMacd && <div ref={macdRef} className="w-full" />}
    </div>
  );
}
