"use client";

import { VT323 } from "next/font/google";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

interface Props {
  content?: string;
}

export function ReportCard({ content }: Props) {
  return (
    <article className="surface p-7 md:p-9 border-l-[8px] border-l-[#FAAD14]">
      <header className="flex flex-wrap items-end justify-between gap-3 mb-5 pb-4 border-b-2 border-[#E8E2D6]">
        <div>
          <div className="tagline mb-1">Báo cáo · Markdown</div>
          <h3
            className={`${vt323.className} text-3xl uppercase tracking-wider text-black leading-none`}
          >
            Báo cáo tổng hợp
          </h3>
        </div>
        <div className="text-[10px] font-mono text-[#555555] uppercase tracking-widest">
          {content
            ? `${content.length.toLocaleString("vi-VN")} ký tự`
            : "đang sinh báo cáo…"}
        </div>
      </header>

      <div className="md-body max-h-[44rem] overflow-auto pr-2">
        {content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        ) : (
          <div className="flex flex-col gap-2 text-[#888888] text-sm">
            <div className="h-3 bg-[var(--bg-warm)] w-3/4 animate-pulse" />
            <div className="h-3 bg-[var(--bg-warm)] w-2/3 animate-pulse" />
            <div className="h-3 bg-[var(--bg-warm)] w-4/5 animate-pulse" />
            <div className="text-xs text-[#888888] mt-3 italic">
              Báo cáo Markdown sẽ xuất hiện ngay sau khi CIO ra quyết định cho mọi mã.
            </div>
          </div>
        )}
      </div>
    </article>
  );
}
