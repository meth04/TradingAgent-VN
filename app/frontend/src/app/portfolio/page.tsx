"use client";

import { useEffect, useState } from "react";
import { VT323 } from "next/font/google";
import { getPortfolio, savePortfolio, getPortfolioValue } from "@/lib/api";
import type { Portfolio, PortfolioValue } from "@/lib/types";
import { TICKERS } from "../page";
import { HeroBlock } from "@/components/HeroBlock";
import { StatBlock } from "@/components/StatBlock";
import { Sidebar, SidebarDivider } from "@/components/Sidebar";
import { formatVnd, formatVndShort } from "@/lib/format";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface DraftRow {
  id: number;
  ticker: string;
  quantity: string;
  avg_price: string;
}

let nextId = 1;

export default function PortfolioPage() {
  const [cash, setCash] = useState<string>("0");
  const [rows, setRows] = useState<DraftRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string>("");
  const [err, setErr] = useState<string>("");
  const [value, setValue] = useState<PortfolioValue | null>(null);
  const [loadingValue, setLoadingValue] = useState(false);

  async function load() {
    try {
      const p = await getPortfolio();
      setCash(String(Math.round(p.cash || 0)));
      setRows(
        (p.positions || []).map((pos) => ({
          id: nextId++,
          ticker: pos.ticker,
          quantity: String(pos.quantity),
          avg_price: String(Math.round(pos.avg_price)),
        })),
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  }

  async function refreshValue() {
    setLoadingValue(true);
    try {
      const v = await getPortfolioValue();
      setValue(v);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingValue(false);
    }
  }

  useEffect(() => {
    load().then(() => refreshValue());
  }, []);

  function addRow() {
    setRows((r) => [
      ...r,
      { id: nextId++, ticker: "FPT", quantity: "", avg_price: "" },
    ]);
  }
  function removeRow(id: number) {
    setRows((r) => r.filter((x) => x.id !== id));
  }
  function updateRow(id: number, patch: Partial<DraftRow>) {
    setRows((r) => r.map((x) => (x.id === id ? { ...x, ...patch } : x)));
  }

  async function save() {
    setSaving(true);
    setErr("");
    try {
      const p: Portfolio = {
        cash: Number(cash) || 0,
        positions: rows
          .filter((r) => r.ticker && Number(r.quantity) > 0)
          .map((r) => ({
            ticker: r.ticker.toUpperCase(),
            quantity: Number(r.quantity) || 0,
            avg_price: Number(r.avg_price) || 0,
          })),
      };
      await savePortfolio(p);
      setSavedAt(new Date().toLocaleTimeString("vi-VN"));
      await refreshValue();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  const heroChips = value
    ? [
        {
          label: "NAV",
          value: `${formatVndShort(value.total_market_value)}đ`,
          accent: "gold" as const,
        },
        {
          label: "Tiền mặt",
          value: `${formatVndShort(value.cash)}đ`,
          accent: "coral" as const,
        },
        {
          label: "P&L",
          value: `${value.total_pnl >= 0 ? "+" : ""}${formatVndShort(value.total_pnl)}đ`,
          accent: value.total_pnl >= 0 ? ("green" as const) : ("red" as const),
        },
      ]
    : [{ label: "NAV", value: "—", accent: "gold" as const }];

  return (
    <div className="w-full px-4 py-8 md:px-8 md:py-10">
      <div className="mx-auto w-full max-w-[1500px] grid lg:grid-cols-[340px_minmax(0,1fr)] gap-6">
        {/* SIDEBAR: form */}
        <Sidebar
          footer={
            <div className="flex flex-col gap-2">
              <button
                onClick={save}
                disabled={saving}
                className="btn-primary w-full text-center"
              >
                {saving ? "Đang lưu..." : "Lưu portfolio"}
              </button>
              {savedAt && (
                <div className="text-[10px] text-[#555555] font-mono">
                  ✓ Lưu lúc {savedAt}
                </div>
              )}
              <button
                onClick={refreshValue}
                disabled={loadingValue}
                className="btn-ghost w-full text-center mt-1"
              >
                {loadingValue ? "Đang tải..." : "↻ Làm mới giá"}
              </button>
            </div>
          }
        >
          <div>
            <div className="flex items-center gap-2 mb-3">
              <span className="tagline">Bước 01</span>
              <h3
                className={`${vt323.className} text-xl uppercase tracking-[0.06em] text-black leading-none`}
              >
                Tiền mặt
              </h3>
            </div>
            <input
              type="number"
              value={cash}
              onChange={(e) => setCash(e.target.value)}
              className="w-full px-3 py-2.5 font-mono text-right text-base"
            />
            <div className="mt-1 text-[10px] text-[#555555] font-mono">VND</div>
          </div>

          <SidebarDivider />

          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="tagline">Bước 02</span>
                <h3
                  className={`${vt323.className} text-xl uppercase tracking-[0.06em] text-black leading-none`}
                >
                  Vị thế
                </h3>
              </div>
              <span className="badge badge-info">{rows.length}</span>
            </div>

            <div className="flex flex-col gap-1.5">
              {rows.length === 0 && (
                <div className="text-center text-[#888888] py-3 text-[11px] italic">
                  Chưa có vị thế.
                </div>
              )}
              {rows.map((r) => (
                <div
                  key={r.id}
                  className="border-2 border-black bg-white p-2 shadow-[1px_1px_0_#000000] flex flex-col gap-1.5"
                >
                  <div className="flex items-center gap-2">
                    <select
                      value={r.ticker}
                      onChange={(e) => updateRow(r.id, { ticker: e.target.value })}
                      className="flex-1 px-2 py-1 font-mono font-bold text-black text-sm"
                    >
                      {TICKERS.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => removeRow(r.id)}
                      className="text-[#B91C1C] hover:bg-[#FBE9E9] w-7 h-7 transition-colors font-bold border-2 border-black bg-white text-base leading-none"
                      title="Xoá"
                    >
                      ×
                    </button>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5">
                    <div>
                      <div className="text-[8px] font-mono uppercase tracking-[0.16em] text-[#555555] mb-0.5">
                        SL
                      </div>
                      <input
                        type="number"
                        value={r.quantity}
                        onChange={(e) =>
                          updateRow(r.id, { quantity: e.target.value })
                        }
                        className="w-full px-2 py-1 font-mono text-right text-xs"
                        placeholder="0"
                      />
                    </div>
                    <div>
                      <div className="text-[8px] font-mono uppercase tracking-[0.16em] text-[#555555] mb-0.5">
                        Giá TB
                      </div>
                      <input
                        type="number"
                        value={r.avg_price}
                        onChange={(e) =>
                          updateRow(r.id, { avg_price: e.target.value })
                        }
                        className="w-full px-2 py-1 font-mono text-right text-xs"
                        placeholder="0"
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <button onClick={addRow} className="btn-ghost w-full text-center mt-2">
              + Thêm cổ phiếu
            </button>
          </div>
        </Sidebar>

        {/* CANVAS */}
        <div className="min-w-0">
          <HeroBlock
            tagline="Portfolio · Live Pricing"
            title="Danh mục đầu tư"
            subtitle="Quản lý cash và positions ở thanh bên trái, lưu vào app/data/portfolio.json. Giá real-time từ data/vnstock.db (read-only, cache 30 phút)."
            rightChips={heroChips}
          />

          {err && (
            <div className="pixel-border bg-[#FBE9E9] border-[#EF4444] p-4 text-[#B91C1C] text-sm font-mono mb-6">
              {err}
            </div>
          )}

          {!value ? (
            <div className="pixel-border surface-warm p-10 text-center text-[#555555] font-mono">
              Đang tính giá trị danh mục...
            </div>
          ) : (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatBlock
                  label="Tổng giá trị"
                  value={`${formatVnd(value.total_market_value)}đ`}
                  tone="gold"
                />
                <StatBlock label="Tiền mặt" value={`${formatVnd(value.cash)}đ`} />
                <StatBlock
                  label="Cổ phiếu"
                  value={`${formatVnd(value.total_market_value - value.cash)}đ`}
                />
                <StatBlock
                  label="Lãi / Lỗ"
                  tone={value.total_pnl >= 0 ? "green" : "red"}
                  value={`${value.total_pnl >= 0 ? "+" : ""}${formatVndShort(value.total_pnl)}đ`}
                  sub={
                    <span
                      className={
                        value.total_pnl >= 0 ? "text-[#0B6E54]" : "text-[#B91C1C]"
                      }
                    >
                      {value.total_pnl_pct >= 0 ? "+" : ""}
                      {value.total_pnl_pct.toFixed(2)}%
                    </span>
                  }
                />
              </div>

              <div className="pixel-border bg-white p-5">
                <div className="flex items-center gap-3 mb-4">
                  <span className="tagline">Chi tiết</span>
                  <h3
                    className={`${vt323.className} text-2xl uppercase tracking-[0.06em] text-black leading-none`}
                  >
                    Per-ticker breakdown
                  </h3>
                  <div className="section-rule" />
                </div>

                <table className="w-full text-sm font-mono border-collapse">
                  <thead>
                    <tr className="bg-[var(--bg-warm)] uppercase text-[9px] tracking-[0.16em] text-[#555555]">
                      <th className="text-left p-2 border-2 border-black font-bold">
                        Ticker
                      </th>
                      <th className="text-right p-2 border-2 border-black font-bold">
                        SL
                      </th>
                      <th className="text-right p-2 border-2 border-black font-bold">
                        Giá TB
                      </th>
                      <th className="text-right p-2 border-2 border-black font-bold">
                        Hiện tại
                      </th>
                      <th className="text-right p-2 border-2 border-black font-bold">
                        Giá trị
                      </th>
                      <th className="text-right p-2 border-2 border-black font-bold">
                        P&L
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {value.positions.length === 0 && (
                      <tr>
                        <td
                          colSpan={6}
                          className="text-center text-[#888888] py-4 italic border-2 border-black"
                        >
                          Không có vị thế.
                        </td>
                      </tr>
                    )}
                    {value.positions.map((p) => (
                      <tr key={p.ticker} className="hover:bg-[var(--bg-warm)]">
                        <td className="p-2 border-2 border-black font-bold text-black">
                          {p.ticker}
                        </td>
                        <td className="p-2 border-2 border-black text-right">
                          {formatVnd(p.quantity)}
                        </td>
                        <td className="p-2 border-2 border-black text-right text-[#555555]">
                          {formatVnd(p.avg_price)}
                        </td>
                        <td className="p-2 border-2 border-black text-right">
                          {formatVnd(p.current_price)}
                        </td>
                        <td className="p-2 border-2 border-black text-right font-bold">
                          {formatVndShort(p.market_value)}đ
                        </td>
                        <td
                          className={`p-2 border-2 border-black text-right font-bold ${
                            p.pnl >= 0 ? "text-[#0B6E54]" : "text-[#B91C1C]"
                          }`}
                        >
                          {p.pnl >= 0 ? "+" : ""}
                          {formatVndShort(p.pnl)}đ
                          <div className="text-[10px] font-mono opacity-80">
                            {p.pnl_pct >= 0 ? "+" : ""}
                            {p.pnl_pct.toFixed(2)}%
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
