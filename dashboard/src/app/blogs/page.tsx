import { loadBlogPosts, getPlaybackDates, loadStates } from "@/lib/data";
import { BlogFeed } from "@/components/BlogFeed";
import { PlaybackInit } from "@/components/PlaybackInit";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export default function BlogsPage() {
  const posts = loadBlogPosts();
  const states = loadStates();
  const playbackDates = getPlaybackDates(states);

  return (
    <div className="w-full px-4 py-14 md:px-8 md:py-16">
      <PlaybackInit dates={playbackDates} />
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-12">
        <section className="grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_340px] lg:items-start">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">
              Kho evidence theo ngày
            </div>
            <h1 className={`${vt323.className} text-6xl uppercase tracking-[0.08em] text-[#000000] md:text-7xl`}>
              Báo cáo
            </h1>
            <p className="max-w-4xl text-sm leading-8 text-[#666666] md:text-[15px]">
              Đây là bề mặt archive cho các báo cáo được sinh ra từ những Workflow trong hệ thống hỗ trợ phân tích đầu tư chứng khoán. Mỗi báo cáo là một artifact mô tả lại bối cảnh, tín hiệu và quyết định tại một mốc backtest cụ thể, phục vụ trực tiếp cho việc trình bày và bảo vệ luận điểm khóa luận.
            </p>
          </div>

          <div className="grid gap-4">
            <div className="pixel-border bg-[var(--surface-warm)] p-6 md:p-7">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Vai trò của trang này
              </div>
              <p className="mt-3 text-sm leading-6 text-[#666666]">
                Đây là kho artifact để chứng minh hệ thống đa tác tử đã sinh ra đầu ra gì, vào thời điểm nào, và dưới ngữ cảnh nào.
              </p>
            </div>

            <div className="pixel-border bg-[var(--surface-tint)] p-6 md:p-7">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Cách đọc hiệu quả
              </div>
              <ul className="mt-3 space-y-3 text-sm leading-6 text-[#666666]">
                <li>• Dùng timeline toàn cục để giới hạn báo cáo theo đúng mốc backtest đang trình bày.</li>
                <li>• Đọc cùng với Workflow để hiểu cấu trúc sinh ra từng loại đầu ra.</li>
                <li>• Đối chiếu với Leaderboard và Trading View để nối báo cáo với số liệu và hành động giao dịch.</li>
              </ul>
            </div>
          </div>
        </section>

        <section className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div className="min-h-[500px]">
            <BlogFeed posts={posts} playbackDates={playbackDates} />
          </div>

          <aside className="space-y-4 lg:sticky lg:top-24">
            <div className="pixel-border bg-[#FFFFFF] p-5">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Tóm tắt archive
              </div>
              <div className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
                {posts.length}
              </div>
              <p className="mt-3 text-sm leading-6 text-[#666666]">
                artifact báo cáo hiện có trong repository để phục vụ trình bày và rà soát.
              </p>
            </div>

            <div className="pixel-border bg-[var(--surface-warm)] p-5">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Ý nghĩa từng báo cáo
              </div>
              <p className="mt-3 text-sm leading-6 text-[#666666]">
                Mỗi thẻ phản ánh cách một Workflow diễn giải bối cảnh, tín hiệu và hành động tại ngày đó. Đây là lớp giải thích bằng văn bản của hệ thống multi agent.
              </p>
            </div>

            <div className="pixel-border bg-[var(--surface-tint)] p-5">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Liên hệ với đề tài
              </div>
              <p className="mt-3 text-sm leading-6 text-[#666666]">
                Với đề tài “Ứng dụng multi agent trong hỗ trợ phân tích đầu tư chứng khoán”, trang này đóng vai trò là trực quan hóa các đầu ra do Workflow tạo ra để phục vụ giải thích, đối chiếu và phản biện.
              </p>
            </div>

            <div className="pixel-border bg-[#FFFFFF] p-5">
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Nhóm artifact chính
              </div>
              <p className="mt-3 text-sm leading-6 text-[#666666]">
                Khu vực chính bên trái là dòng artifact theo ngày. Mỗi nhóm tương ứng với một mốc thời gian trong backtest và cho phép đọc lại tiến trình nghiên cứu theo trật tự thời gian.
              </p>
            </div>
          </aside>
        </section>
      </div>
    </div>
  );
}
