"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BlogCard } from "@/components/BlogCard";
import { BlogPost } from "@/lib/data";
import { usePlayback } from "@/contexts/PlaybackContext";
import { VT323 } from "next/font/google";
import { formatDate } from "@/lib/format";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

const PAGE_SIZE = 6;

export function BlogFeed({ posts, playbackDates }: { posts: BlogPost[]; playbackDates: string[] }) {
  const { currentDate, setDates, dates } = usePlayback();
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const loaderRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!dates.length && playbackDates.length) {
      setDates(playbackDates);
    }
  }, [dates.length, playbackDates, setDates]);

  const postsByDate = useMemo(() => {
    const cutoff = currentDate || playbackDates[playbackDates.length - 1];

    const grouped = new Map<string, Record<string, BlogPost>>();

    posts.forEach((p) => {
      if (p.date <= (cutoff || "")) {
        const stripped = p.content
          .replace(/^#.*$/gm, "")
          .replace(/Ledger context:\s*/gi, "")
          .replace(/\[\s*\]/g, "")
          .replace(/No trades executed today\.?/gi, "")
          .trim();

        if (stripped.length > 100) {
          if (!grouped.has(p.date)) grouped.set(p.date, {});
          grouped.get(p.date)![p.workflow.toLowerCase()] = p;
        }
      }
    });

    return Array.from(grouped.entries()).sort((a, b) => b[0].localeCompare(a[0]));
  }, [posts, currentDate, playbackDates]);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
  }, [currentDate]);

  useEffect(() => {
    if (!loaderRef.current) return;
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          setVisibleCount((prev) => Math.min(prev + PAGE_SIZE, postsByDate.length));
        }
      });
    });
    observer.observe(loaderRef.current);
    return () => observer.disconnect();
  }, [postsByDate.length]);

  const workflowOrder = ["traditional", "kelly", "markowitz", "cognitive"];

  return (
    <div className="flex flex-col gap-16">
      {postsByDate.slice(0, visibleCount).map(([date, dailyPosts]) => {
        const postsArray = workflowOrder.map((wf) => dailyPosts[wf]).filter(Boolean);
        if (postsArray.length === 0) return null;

        return (
          <section key={date} className="flex flex-col gap-7">
            <div className="flex flex-col gap-4 border-b-2 border-border pb-5 md:flex-row md:items-end md:justify-between">
              <div className="space-y-2">
                <div className="text-[10px] uppercase tracking-[0.22em] text-text-secondary font-mono">
                  Nhóm artifact theo ngày
                </div>
                <h2 className={`${vt323.className} text-5xl uppercase tracking-[0.08em] text-[#000000]`}>
                  {formatDate(date)}
                </h2>
              </div>
              <div className="text-[11px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                {postsArray.length} báo cáo Workflow khả dụng tại mốc này
              </div>
            </div>

            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              {postsArray.map((post) => (
                <div key={post.workflow} className="flex flex-col">
                  <BlogCard post={post} />
                </div>
              ))}
            </div>
          </section>
        );
      })}
      <div ref={loaderRef} className="h-10" />
    </div>
  );
}
