"use client";

import { useEffect, useMemo, useState } from "react";
import { PortfolioState } from "@/lib/data";
import { usePlayback } from "@/contexts/PlaybackContext";
import { formatDate } from "@/lib/format";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface PortfolioData {
  workflow: string;
  cash: number;
  totalEquity: number;
  positions: Array<{
    ticker: string;
    quantity: number;
    value: number;
    weightPct: number;
  }>;
  cashWeightPct: number;
}

const COLORS = [
  "#FF6B6B", // Coral Red
  "#4ECDC4", // Turquoise
  "#45B7D1", // Sky Blue
  "#FFA07A", // Light Salmon
  "#98D8C8", // Mint
  "#F7DC6F", // Soft Yellow
  "#BB8FCE", // Lavender
  "#85C1E2", // Powder Blue
  "#F8B739", // Golden
  "#52B788", // Forest Green
  "#E76F51", // Terracotta
  "#2A9D8F", // Teal
  "#E9C46A", // Sand
  "#F4A261", // Sandy Brown
  "#264653", // Dark Slate
];

function getColorForTicker(ticker: string, index: number): string {
  return COLORS[index % COLORS.length];
}

function EquityChart({
  equityHistory,
  dates,
  width = 800,
  height = 300,
}: {
  equityHistory: number[];
  dates: string[];
  width?: number;
  height?: number;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [mousePosition, setMousePosition] = useState<{ x: number; y: number } | null>(null);

  if (!equityHistory || equityHistory.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-[#666666] font-mono text-sm">
        Không có dữ liệu equity history
      </div>
    );
  }

  const padding = { top: 20, right: 40, bottom: 40, left: 80 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Find min and max values
  const minValue = Math.min(...equityHistory);
  const maxValue = Math.max(...equityHistory);
  const valueRange = maxValue - minValue;
  const yMin = minValue - valueRange * 0.1;
  const yMax = maxValue + valueRange * 0.1;

  // Create points for the line
  const points = equityHistory.map((value, index) => {
    const x = padding.left + (index / (equityHistory.length - 1)) * chartWidth;
    const y = padding.top + chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight;
    return { x, y, value, date: dates[index] || "" };
  });

  // Create path data
  const pathData = points
    .map((point, index) => {
      if (index === 0) return `M ${point.x} ${point.y}`;
      return `L ${point.x} ${point.y}`;
    })
    .join(" ");

  // Create area fill path (from line to bottom)
  const areaPath = `${pathData} L ${points[points.length - 1].x} ${padding.top + chartHeight} L ${points[0].x} ${padding.top + chartHeight} Z`;

  // Y-axis labels
  const yTicks = 5;
  const yLabels = Array.from({ length: yTicks }, (_, i) => {
    const value = yMin + (yMax - yMin) * (i / (yTicks - 1));
    const y = padding.top + chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight;
    return { value, y };
  });

  // X-axis labels (show first, middle, last)
  const xLabels = [
    { date: dates[0], x: padding.left },
    { date: dates[Math.floor(dates.length / 2)], x: padding.left + chartWidth / 2 },
    { date: dates[dates.length - 1], x: padding.left + chartWidth },
  ].filter((label) => label.date);

  // Handle mouse move for tooltip
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // Check if mouse is within chart area
    if (x < padding.left || x > padding.left + chartWidth || y < padding.top || y > padding.top + chartHeight) {
      setHoveredIndex(null);
      setMousePosition(null);
      return;
    }

    // Find closest data point
    const relativeX = x - padding.left;
    const index = Math.round((relativeX / chartWidth) * (equityHistory.length - 1));
    
    if (index >= 0 && index < equityHistory.length) {
      setHoveredIndex(index);
      setMousePosition({ x, y });
    }
  };

  const handleMouseLeave = () => {
    setHoveredIndex(null);
    setMousePosition(null);
  };

  return (
    <div className="relative">
      <svg 
        width={width} 
        height={height} 
        className="w-full"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
      {/* Grid lines */}
      {yLabels.map((label, idx) => (
        <line
          key={idx}
          x1={padding.left}
          y1={label.y}
          x2={padding.left + chartWidth}
          y2={label.y}
          stroke="#E5E5E5"
          strokeWidth="1"
          strokeDasharray="4 4"
        />
      ))}

      {/* Area fill */}
      <path d={areaPath} fill="url(#gradient)" opacity="0.2" />

      {/* Gradient definition */}
      <defs>
        <linearGradient id="gradient" x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor="#10A37F" stopOpacity="0.8" />
          <stop offset="100%" stopColor="#10A37F" stopOpacity="0.1" />
        </linearGradient>
      </defs>

      {/* Line */}
      <path d={pathData} fill="none" stroke="#10A37F" strokeWidth="3" />

      {/* Points */}
      {points.map((point, idx) => (
        <circle key={idx} cx={point.x} cy={point.y} r="3" fill="#10A37F" className="hover:r-5 cursor-pointer">
          <title>{`${point.date}: ${point.value.toLocaleString("vi-VN")} VND`}</title>
        </circle>
      ))}

      {/* Y-axis */}
      <line
        x1={padding.left}
        y1={padding.top}
        x2={padding.left}
        y2={padding.top + chartHeight}
        stroke="#666666"
        strokeWidth="2"
      />

      {/* Y-axis labels */}
      {yLabels.map((label, idx) => (
        <text
          key={idx}
          x={padding.left - 10}
          y={label.y}
          textAnchor="end"
          dominantBaseline="middle"
          className="text-[11px] font-mono fill-[#666666]"
        >
          {(label.value / 1000000).toFixed(0)}M
        </text>
      ))}

      {/* X-axis */}
      <line
        x1={padding.left}
        y1={padding.top + chartHeight}
        x2={padding.left + chartWidth}
        y2={padding.top + chartHeight}
        stroke="#666666"
        strokeWidth="2"
      />

      {/* X-axis labels */}
      {xLabels.map((label, idx) => (
        <text
          key={idx}
          x={label.x}
          y={padding.top + chartHeight + 25}
          textAnchor="middle"
          className="text-[10px] font-mono fill-[#666666]"
        >
          {label.date}
        </text>
      ))}

      {/* Hover line and point */}
      {hoveredIndex !== null && (
        <>
          {/* Vertical line */}
          <line
            x1={points[hoveredIndex].x}
            y1={padding.top}
            x2={points[hoveredIndex].x}
            y2={padding.top + chartHeight}
            stroke="#666666"
            strokeWidth="1"
            strokeDasharray="4 2"
            opacity="0.6"
          />
          
          {/* Point */}
          <circle
            cx={points[hoveredIndex].x}
            cy={points[hoveredIndex].y}
            r="6"
            fill="#10A37F"
            stroke="#FFFFFF"
            strokeWidth="2"
          />
        </>
      )}
    </svg>

    {/* Tooltip */}
    {hoveredIndex !== null && mousePosition && (
      <div
        className="absolute pointer-events-none z-50"
        style={{
          left: `${mousePosition.x + 15}px`,
          top: `${mousePosition.y - 60}px`,
        }}
      >
        <div className="bg-white border-2 border-[#241C39] shadow-[4px_4px_0_rgba(36,28,57,0.96)] p-3 min-w-[160px]">
          <div className="text-[10px] font-mono text-[#666666] mb-2 uppercase tracking-wider">
            {dates[hoveredIndex]}
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[11px] font-mono text-[#000000]">Tổng NAV</span>
              <span className="text-[13px] font-mono font-bold text-[#10A37F]">
                {(equityHistory[hoveredIndex] / 1000000).toFixed(2)}M
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] font-mono text-[#666666]">Chi tiết</span>
              <span className="text-[10px] font-mono text-[#666666]">
                {equityHistory[hoveredIndex].toLocaleString("vi-VN")} ₫
              </span>
            </div>
          </div>
        </div>
      </div>
    )}
  </div>
  );
}

interface BenchmarkData {
  date: string;
  value: number;
}

function PerformanceComparisonChart({
  portfolioData,
  benchmarkData,
  benchmarkName,
  dates,
  width = 1000,
  height = 400,
}: {
  portfolioData: number[];
  benchmarkData: BenchmarkData[];
  benchmarkName: string;
  dates: string[];
  width?: number;
  height?: number;
}) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [mousePosition, setMousePosition] = useState<{ x: number; y: number } | null>(null);

  if (!portfolioData || portfolioData.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-[#666666] font-mono text-sm">
        Không có dữ liệu để so sánh
      </div>
    );
  }

  const padding = { top: 40, right: 100, bottom: 50, left: 80 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  // Normalize portfolio data to percentage (base 100)
  const normalizedPortfolio = portfolioData.map((value) => (value / portfolioData[0]) * 100);

  // Create date-aligned data
  const alignedData = dates.map((date, idx) => {
    const benchmarkPoint = benchmarkData.find((d) => d.date === date);
    
    return {
      date,
      portfolio: normalizedPortfolio[idx] || 100,
      benchmark: benchmarkPoint?.value || 100,
    };
  });

  console.log('Aligned data sample:', alignedData.slice(0, 5));
  console.log('Portfolio range:', Math.min(...normalizedPortfolio), '-', Math.max(...normalizedPortfolio));
  console.log('Benchmark range:', Math.min(...alignedData.map(d => d.benchmark)), '-', Math.max(...alignedData.map(d => d.benchmark)));

  // Find min and max values across both series
  const allValues = alignedData.flatMap((d) => [d.portfolio, d.benchmark]);
  const minValue = Math.min(...allValues);
  const maxValue = Math.max(...allValues);
  const valueRange = maxValue - minValue;
  const yMin = Math.max(0, minValue - valueRange * 0.1);
  const yMax = maxValue + valueRange * 0.1;

  // Create points for each series
  const createPoints = (data: number[], color: string) => {
    return data.map((value, index) => {
      const x = padding.left + (index / (data.length - 1)) * chartWidth;
      const y = padding.top + chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight;
      return { x, y, value, date: dates[index] || "", color };
    });
  };

  const portfolioPoints = createPoints(
    alignedData.map((d) => d.portfolio),
    "#10A37F"
  );
  const benchmarkPoints = createPoints(
    alignedData.map((d) => d.benchmark),
    "#FF6B6B"
  );

  // Create path data for each series
  const createPath = (points: typeof portfolioPoints) => {
    return points
      .map((point, index) => {
        if (index === 0) return `M ${point.x} ${point.y}`;
        return `L ${point.x} ${point.y}`;
      })
      .join(" ");
  };

  const portfolioPath = createPath(portfolioPoints);
  const benchmarkPath = createPath(benchmarkPoints);

  // Y-axis labels
  const yTicks = 6;
  const yLabels = Array.from({ length: yTicks }, (_, i) => {
    const value = yMin + (yMax - yMin) * (i / (yTicks - 1));
    const y = padding.top + chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight;
    return { value, y };
  });

  // X-axis labels (show more points for better readability)
  const xLabelCount = 6;
  const xLabels = Array.from({ length: xLabelCount }, (_, i) => {
    const idx = Math.floor((i / (xLabelCount - 1)) * (dates.length - 1));
    return {
      date: dates[idx],
      x: padding.left + (idx / (dates.length - 1)) * chartWidth,
    };
  }).filter((label) => label.date);

  // Handle mouse move for tooltip
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // Check if mouse is within chart area
    if (x < padding.left || x > padding.left + chartWidth || y < padding.top || y > padding.top + chartHeight) {
      setHoveredIndex(null);
      setMousePosition(null);
      return;
    }

    // Find closest data point
    const relativeX = x - padding.left;
    const index = Math.round((relativeX / chartWidth) * (dates.length - 1));
    
    if (index >= 0 && index < dates.length) {
      setHoveredIndex(index);
      setMousePosition({ x, y });
    }
  };

  const handleMouseLeave = () => {
    setHoveredIndex(null);
    setMousePosition(null);
  };

  return (
    <div className="relative">
      <svg 
        width={width} 
        height={height} 
        className="w-full"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
      {/* Grid lines */}
      {yLabels.map((label, idx) => (
        <line
          key={idx}
          x1={padding.left}
          y1={label.y}
          x2={padding.left + chartWidth}
          y2={label.y}
          stroke="#E5E5E5"
          strokeWidth="1"
          strokeDasharray="4 4"
        />
      ))}

      {/* Baseline at 100 */}
      <line
        x1={padding.left}
        y1={padding.top + chartHeight - ((100 - yMin) / (yMax - yMin)) * chartHeight}
        x2={padding.left + chartWidth}
        y2={padding.top + chartHeight - ((100 - yMin) / (yMax - yMin)) * chartHeight}
        stroke="#999999"
        strokeWidth="1.5"
        strokeDasharray="8 4"
        opacity="0.5"
      />

      {/* Benchmark line */}
      <path d={benchmarkPath} fill="none" stroke="#FF6B6B" strokeWidth="3" opacity="0.85" />

      {/* Portfolio line (on top) */}
      <path d={portfolioPath} fill="none" stroke="#10A37F" strokeWidth="3.5" />

      {/* Y-axis */}
      <line
        x1={padding.left}
        y1={padding.top}
        x2={padding.left}
        y2={padding.top + chartHeight}
        stroke="#666666"
        strokeWidth="2"
      />

      {/* Y-axis labels */}
      {yLabels.map((label, idx) => (
        <text
          key={idx}
          x={padding.left - 10}
          y={label.y}
          textAnchor="end"
          dominantBaseline="middle"
          className="text-[11px] font-mono fill-[#666666]"
        >
          {label.value.toFixed(0)}%
        </text>
      ))}

      {/* Y-axis title */}
      <text
        x={padding.left - 55}
        y={padding.top + chartHeight / 2}
        textAnchor="middle"
        dominantBaseline="middle"
        className="text-[11px] font-mono fill-[#666666] uppercase tracking-wider"
        transform={`rotate(-90, ${padding.left - 55}, ${padding.top + chartHeight / 2})`}
      >
        Hiệu suất (%)
      </text>

      {/* X-axis */}
      <line
        x1={padding.left}
        y1={padding.top + chartHeight}
        x2={padding.left + chartWidth}
        y2={padding.top + chartHeight}
        stroke="#666666"
        strokeWidth="2"
      />

      {/* X-axis labels */}
      {xLabels.map((label, idx) => (
        <text
          key={idx}
          x={label.x}
          y={padding.top + chartHeight + 25}
          textAnchor="middle"
          className="text-[10px] font-mono fill-[#666666]"
        >
          {label.date}
        </text>
      ))}

      {/* Legend */}
      <g transform={`translate(${padding.left + chartWidth + 20}, ${padding.top + 20})`}>
        {/* Portfolio */}
        <g transform="translate(0, 0)">
          <line x1="0" y1="0" x2="35" y2="0" stroke="#10A37F" strokeWidth="3.5" />
          <text x="45" y="0" dominantBaseline="middle" className="text-[12px] font-mono fill-[#000000] font-bold">
            Danh mục
          </text>
        </g>

        {/* Benchmark */}
        <g transform="translate(0, 30)">
          <line x1="0" y1="0" x2="35" y2="0" stroke="#FF6B6B" strokeWidth="3" />
          <text x="45" y="0" dominantBaseline="middle" className="text-[12px] font-mono fill-[#000000] font-bold">
            {benchmarkName}
          </text>
        </g>
      </g>

      {/* Hover line and points */}
      {hoveredIndex !== null && (
        <>
          {/* Vertical line */}
          <line
            x1={portfolioPoints[hoveredIndex].x}
            y1={padding.top}
            x2={portfolioPoints[hoveredIndex].x}
            y2={padding.top + chartHeight}
            stroke="#666666"
            strokeWidth="1"
            strokeDasharray="4 2"
            opacity="0.6"
          />
          
          {/* Portfolio point */}
          <circle
            cx={portfolioPoints[hoveredIndex].x}
            cy={portfolioPoints[hoveredIndex].y}
            r="5"
            fill="#10A37F"
            stroke="#FFFFFF"
            strokeWidth="2"
          />
          
          {/* Benchmark point */}
          <circle
            cx={benchmarkPoints[hoveredIndex].x}
            cy={benchmarkPoints[hoveredIndex].y}
            r="5"
            fill="#FF6B6B"
            stroke="#FFFFFF"
            strokeWidth="2"
          />
        </>
      )}
    </svg>

    {/* Tooltip */}
    {hoveredIndex !== null && mousePosition && (
      <div
        className="absolute pointer-events-none z-50"
        style={{
          left: `${mousePosition.x + 15}px`,
          top: `${mousePosition.y - 80}px`,
        }}
      >
        <div className="bg-white border-2 border-[#241C39] shadow-[4px_4px_0_rgba(36,28,57,0.96)] p-3 min-w-[180px]">
          <div className="text-[10px] font-mono text-[#666666] mb-2 uppercase tracking-wider">
            {dates[hoveredIndex]}
          </div>
          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-[#10A37F] rounded-sm"></div>
                <span className="text-[11px] font-mono text-[#000000]">Danh mục</span>
              </div>
              <span className="text-[12px] font-mono font-bold text-[#10A37F]">
                {alignedData[hoveredIndex].portfolio.toFixed(2)}%
              </span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <div className="w-3 h-3 bg-[#FF6B6B] rounded-sm"></div>
                <span className="text-[11px] font-mono text-[#000000]">{benchmarkName}</span>
              </div>
              <span className="text-[12px] font-mono font-bold text-[#FF6B6B]">
                {alignedData[hoveredIndex].benchmark.toFixed(2)}%
              </span>
            </div>
            <div className="pt-1.5 mt-1.5 border-t border-[#E5E5E5]">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[10px] font-mono text-[#666666]">Chênh lệch</span>
                <span className={`text-[11px] font-mono font-bold ${
                  alignedData[hoveredIndex].portfolio - alignedData[hoveredIndex].benchmark >= 0 
                    ? 'text-[#10A37F]' 
                    : 'text-[#FF6B6B]'
                }`}>
                  {(alignedData[hoveredIndex].portfolio - alignedData[hoveredIndex].benchmark >= 0 ? '+' : '')}
                  {(alignedData[hoveredIndex].portfolio - alignedData[hoveredIndex].benchmark).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    )}
  </div>
  );
}

export function PortfolioClient({
  states,
  playbackDates,
}: {
  states: Record<string, PortfolioState>;
  playbackDates: string[];
}) {
  const { currentDate, setCurrentDate, setDates } = usePlayback();
  const [selectedWorkflow, setSelectedWorkflow] = useState<string>("");
  const [currentPrices, setCurrentPrices] = useState<Record<string, number>>({});
  const [loadingPrices, setLoadingPrices] = useState(false);
  const [benchmarkData, setBenchmarkData] = useState<{
    data: BenchmarkData[];
    name: string;
  }>({ data: [], name: 'VN30' });
  const [loadingBenchmark, setLoadingBenchmark] = useState(false);

  useEffect(() => {
    if (!playbackDates.length) return;
    if (!currentDate) {
      setCurrentDate(playbackDates[playbackDates.length - 1]);
    }
    if (!selectedWorkflow) {
      const workflows = Object.keys(states);
      if (workflows.length) {
        setSelectedWorkflow(workflows[0]);
      }
    }
    setDates(playbackDates);
  }, [playbackDates, currentDate, setCurrentDate, selectedWorkflow, setDates, states]);

  // Fetch current prices when workflow changes
  useEffect(() => {
    if (!selectedWorkflow || !states[selectedWorkflow]) return;

    const state = states[selectedWorkflow];
    if (!state.positions || typeof state.positions !== "object") return;

    const tickers = Object.keys(state.positions);
    if (tickers.length === 0) return;

    setLoadingPrices(true);
    fetch(`/api/prices?tickers=${tickers.join(",")}`)
      .then((res) => res.json())
      .then((prices) => {
        setCurrentPrices(prices);
        setLoadingPrices(false);
      })
      .catch((err) => {
        console.error("Failed to fetch prices:", err);
        setLoadingPrices(false);
      });
  }, [selectedWorkflow, states]);

  // Fetch benchmark data when playback dates change
  useEffect(() => {
    if (playbackDates.length < 2) return;

    const startDate = playbackDates[0];
    const endDate = playbackDates[playbackDates.length - 1];

    setLoadingBenchmark(true);
    fetch(`/api/benchmark?start=${startDate}&end=${endDate}`)
      .then((res) => res.json())
      .then((data) => {
        console.log('Benchmark data received:', data);
        setBenchmarkData({
          data: data.benchmark || [],
          name: data.benchmarkName || 'VN30',
        });
        setLoadingBenchmark(false);
      })
      .catch((err) => {
        console.error("Failed to fetch benchmark data:", err);
        setLoadingBenchmark(false);
      });
  }, [playbackDates]);

  const portfolioData = useMemo(() => {
    if (!selectedWorkflow || !states[selectedWorkflow]) return null;
    if (Object.keys(currentPrices).length === 0 && loadingPrices) return null;

    const state = states[selectedWorkflow];
    const totalEquity = state.equity_history?.[state.equity_history.length - 1] || 0;
    const cash = state.cash || 0;

    const positions: PortfolioData["positions"] = [];
    if (state.positions && typeof state.positions === "object") {
      Object.entries(state.positions).forEach(([ticker, posData]: [string, any]) => {
        if (posData && typeof posData === "object") {
          // Handle both old format (quantity/price) and new format (lots)
          let quantity = 0;
          
          if (posData.lots && Array.isArray(posData.lots)) {
            // New format: sum up all lots
            posData.lots.forEach((lot: any) => {
              quantity += lot.qty || 0;
            });
          } else {
            // Old format: direct quantity
            quantity = posData.quantity || posData.qty || 0;
          }

          if (quantity > 0) {
            // Use current market price if available
            const currentPrice = currentPrices[ticker] || 0;
            const value = quantity * currentPrice;
            
            if (value > 0) {
              positions.push({
                ticker,
                quantity,
                value,
                weightPct: totalEquity > 0 ? (value / totalEquity) * 100 : 0,
              });
            }
          }
        }
      });
    }

    // Sort by value descending
    positions.sort((a, b) => b.value - a.value);

    const cashWeightPct = totalEquity > 0 ? (cash / totalEquity) * 100 : 0;

    return {
      workflow: selectedWorkflow,
      cash,
      totalEquity,
      positions,
      cashWeightPct,
    };
  }, [selectedWorkflow, states, currentPrices, loadingPrices]);

  const playbackLabel = formatDate(currentDate || playbackDates[playbackDates.length - 1] || "");
  const workflows = Object.keys(states).sort();

  const equityDates = useMemo(() => {
    if (!selectedWorkflow || !states[selectedWorkflow]) return [];
    const state = states[selectedWorkflow];
    const equityHistory = state.equity_history || [];
    if (equityHistory.length === 0) return [];

    const workflowLastDate = state.last_date;
    if (workflowLastDate) {
      const endIdx = playbackDates.indexOf(workflowLastDate);
      if (endIdx >= 0) {
        const startIdx = Math.max(0, endIdx - equityHistory.length + 1);
        const alignedDates = playbackDates.slice(startIdx, endIdx + 1);
        if (alignedDates.length === equityHistory.length) {
          return alignedDates;
        }
      }
    }

    if (playbackDates.length >= equityHistory.length) {
      return playbackDates.slice(-equityHistory.length);
    }

    return equityHistory.map((_, idx) => `Day ${idx + 1}`);
  }, [selectedWorkflow, states, playbackDates]);

  return (
    <div className="w-full px-4 py-14 md:px-8 md:py-16">
      <div className="mx-auto flex max-w-7xl flex-col gap-12">
        <section className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-end">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">
              Phân tích danh mục
            </div>
            <h1 className={`${vt323.className} text-6xl uppercase tracking-[0.08em] text-[#000000] md:text-7xl`}>
              Danh mục
            </h1>
            <p className="max-w-3xl text-sm leading-8 text-[#666666] md:text-[15px]">
              Xem tỷ trọng danh mục của từng workflow. Biểu đồ đường thể hiện hiệu suất của danh mục so với VN30.
            </p>
          </div>
          <div className="pixel-border bg-[var(--surface-tint)] p-6 md:p-7">
            <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
              Mốc playback hiện tại
            </div>
            <div className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
              {playbackLabel}
            </div>
            <p className="mt-3 text-sm leading-6 text-[#666666]">
              Dữ liệu danh mục được cắt theo timeline toàn cục của backtest.
            </p>
          </div>
        </section>

        <section className="pixel-border bg-[#FFFFFF] p-6 md:p-8">
          <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-3">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">Workflow</div>
              <div className="relative z-50 font-mono text-sm text-[#000000]">
                <select
                  value={selectedWorkflow}
                  onChange={(e) => setSelectedWorkflow(e.target.value)}
                  className="border-2 border-border bg-[#FFFFFF] px-3 py-2 text-left shadow-[4px_4px_0_rgba(36,28,57,0.96)] cursor-pointer"
                >
                  {workflows.map((wf) => (
                    <option key={wf} value={wf}>
                      {wf}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        </section>

        {portfolioData && (
          <>
            {/* Performance Comparison Chart */}
            <section className="pixel-border bg-[#FFFFFF] p-6 md:p-8">
              <div className="flex flex-col gap-6">
                <div>
                  <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono mb-2">
                    So sánh hiệu suất danh mục với {benchmarkData.name}
                  </div>
                  <p className="text-sm text-[#666666] mb-4">
                    Biểu đồ so sánh hiệu suất của danh mục với chỉ số {benchmarkData.name} (chuẩn hóa về 100%)
                  </p>
                </div>
                {loadingBenchmark ? (
                  <div className="flex items-center justify-center h-64 text-[#666666] font-mono text-sm">
                    Đang tải dữ liệu benchmark...
                  </div>
                ) : (
                  <PerformanceComparisonChart
                    portfolioData={states[selectedWorkflow]?.equity_history || []}
                    benchmarkData={benchmarkData.data}
                    benchmarkName={benchmarkData.name}
                    dates={equityDates}
                    width={1100}
                    height={420}
                  />
                )}
              </div>
            </section>

            {/* Equity Chart */}
            <section className="pixel-border bg-[#FFFFFF] p-6 md:p-8">
              <div className="flex flex-col gap-6">
                <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                  Biểu đồ tài sản theo thời gian
                </div>
                <EquityChart
                  equityHistory={states[selectedWorkflow]?.equity_history || []}
                  dates={equityDates}
                  width={1000}
                  height={350}
                />
              </div>
            </section>

            {/* Portfolio Details */}
            <section className="grid gap-8 lg:grid-cols-[1fr_1fr]">
              <div className="pixel-border bg-[#FFFFFF] p-6 md:p-8">
                <div className="flex flex-col gap-6">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono mb-4">
                      Chi tiết danh mục
                    </div>
                    <div className="space-y-3">
                      <div className="flex justify-between items-center pb-3 border-b-2 border-border">
                        <span className="text-sm font-mono text-[#666666]">Tổng NAV</span>
                        <span className="text-xl font-mono font-bold text-[#000000]">
                          {portfolioData.totalEquity.toLocaleString("vi-VN", {
                            style: "currency",
                            currency: "VND",
                            minimumFractionDigits: 0,
                          })}
                        </span>
                      </div>

                      <div className="flex justify-between items-center pb-3 border-b border-border-light">
                        <span className="text-sm font-mono text-[#666666]">Tiền mặt</span>
                        <div className="text-right">
                          <div className="text-lg font-mono font-bold text-[#000000]">
                            {portfolioData.cash.toLocaleString("vi-VN", {
                              style: "currency",
                              currency: "VND",
                              minimumFractionDigits: 0,
                            })}
                          </div>
                          <div className="text-xs font-mono text-[#999999]">
                            {portfolioData.cashWeightPct.toFixed(2)}%
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div className="pixel-border bg-[#FFFFFF] p-6 md:p-8">
                <div className="flex flex-col gap-6">
                  <div>
                    <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono mb-4">
                      Vị thế ({portfolioData.positions.length} mã)
                    </div>
                    <div className="space-y-2 max-h-96 overflow-y-auto pr-2">
                      {portfolioData.positions.map((pos, idx) => (
                        <div key={pos.ticker} className="flex items-center justify-between text-sm py-2 border-b border-border-light last:border-0">
                          <div className="flex items-center gap-2">
                            <div
                              className="w-4 h-4 rounded-sm flex-shrink-0 border border-border"
                              style={{ backgroundColor: getColorForTicker(pos.ticker, idx) }}
                            />
                            <span className="font-mono font-bold text-[#000000]">{pos.ticker}</span>
                          </div>
                          <div className="text-right">
                            <div className="font-mono font-bold text-[#000000]">{pos.weightPct.toFixed(2)}%</div>
                            <div className="text-xs font-mono text-[#999999]">
                              {pos.quantity.toLocaleString("vi-VN")} cổ
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
