"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BlogPost } from "@/lib/data";
import { VT323 } from "next/font/google";
import { formatDate } from "@/lib/format";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export function BlogCard({ post }: { post: BlogPost }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <article className="pixel-border flex h-full flex-col bg-[#FFFFFF] p-5 md:p-6">
      <header className="border-b border-border-light pb-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
              Artifact báo cáo theo ngày
            </div>
            <h3 className={`${vt323.className} mt-2 text-3xl uppercase tracking-[0.08em] text-[#000000]`}>
              {post.workflow}
            </h3>
          </div>
          <div className="shrink-0 border border-border bg-[var(--surface-tint)] px-3 py-1 text-[10px] uppercase tracking-[0.14em] text-text-secondary font-mono">
            {formatDate(post.date)}
          </div>
        </div>
      </header>

      <div className="relative mt-5 flex-1 overflow-hidden">
        <div
          className="prose prose-sm max-w-none text-[#666666]"
          style={{ maxHeight: expanded ? "none" : "220px", overflow: "hidden" }}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{post.content}</ReactMarkdown>
        </div>
        {!expanded ? (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-[#FFFFFF] to-transparent" />
        ) : null}
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-border-light pt-4">
        <div className="text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">
          Đầu ra phục vụ trình bày và đối chiếu
        </div>
        <button
          className="border border-border bg-[var(--surface-warm)] px-4 py-2 text-[11px] uppercase tracking-[0.14em] text-[#000000] font-mono transition-colors hover:border-[#FAAD14] hover:bg-[#F5F5F5]"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Thu gọn" : "Xem thêm"}
        </button>
      </div>
    </article>
  );
}
