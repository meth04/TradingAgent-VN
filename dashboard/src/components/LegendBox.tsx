import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export function LegendBox() {
  return (
    <div className="pixel-border bg-bg-card p-4 w-60 z-30 shadow-2xl" style={{ position: "absolute", right: "2rem", top: "1rem" }} aria-label="Strategy Legend">
      <div className={`${vt323.className} uppercase text-base tracking-[0.15em] mb-3 text-black border-b-2 border-black pb-1`}>Strategy Legend</div>
      <div className="text-sm font-mono space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">➊</span>
          <span className="text-[#333333]">Traditional</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xl">➋</span>
          <span className="text-[#333333]">Kelly Criterion</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xl">➌</span>
          <span className="text-[#333333]">Markowitz MPT</span>
        </div>
        <div className="border-t-2 border-[#D0D0D0] my-3" />
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-[#666666] mb-1 font-bold">Signal Types</div>
          <div className="flex items-center gap-2">
             <span className="w-3 h-3 rounded-full bg-[#FAAD14] border border-black"></span>
             <span>Mua (Entry)</span>
          </div>
          <div className="flex items-center gap-2">
             <span className="w-3 h-3 rounded-full bg-[#10A37F] border border-black"></span>
             <span>Bán Lãi (Profit)</span>
          </div>
          <div className="flex items-center gap-2">
             <span className="w-3 h-3 rounded-full bg-[#EF4444] border border-black"></span>
             <span>Bán Lỗ (Loss)</span>
          </div>
        </div>
      </div>
    </div>
  );
}
