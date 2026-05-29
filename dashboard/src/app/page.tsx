import { loadBlogPosts, loadStates, getPlaybackDates, loadSummaries } from "@/lib/data";
import { PlaybackInit } from "@/components/PlaybackInit";
import Link from "next/link";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export default function Home() {
  const posts = loadBlogPosts();
  const states = loadStates();
  const summaries = loadSummaries();
  const playbackDates = getPlaybackDates(states);

  const returnValues = summaries
    .map((s) => s.metrics.return_pct)
    .filter((value): value is number => Number.isFinite(value));
  const sharpeValues = summaries
    .map((s) => s.metrics.sharpe)
    .filter((value): value is number => Number.isFinite(value));
  const drawdownValues = summaries
    .map((s) => s.metrics.max_drawdown_pct)
    .filter((value): value is number => Number.isFinite(value));

  const bestReturn = returnValues.length ? Math.max(...returnValues) : 0;
  const topSharpe = sharpeValues.length ? Math.max(...sharpeValues) : 0;
  const maxDD = drawdownValues.length ? Math.min(...drawdownValues) : 0;
  const strategiesCount = summaries.length;

  return (
    <div className="w-full px-4 py-14 md:px-8 md:py-16">
      <PlaybackInit dates={playbackDates} />

      <div className="mx-auto flex w-full max-w-7xl flex-col gap-14">
        <section className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr] lg:items-end">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.32em] text-text-secondary font-mono">
              Tổng quan
            </div>
            <h1 className={`${vt323.className} text-6xl uppercase leading-none tracking-[0.08em] text-[#000000] md:text-8xl`}>
              VnstockTrading
            </h1>
            <p className="max-w-4xl text-sm leading-8 text-[#666666] md:text-[15px]">
              Đây là giao diện trình bày cho một dự án khóa luận AI về phân tích và ra quyết định đầu tư mô phỏng trên thị trường chứng khoán Việt Nam. 
            </p>
          </div>

          <div className="pixel-border bg-[var(--surface-warm)] p-6 md:p-7">
            <div className="text-[10px] uppercase tracking-[0.22em] text-text-secondary font-mono">
              Gợi ý
            </div>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-[#666666]">
              <li>
                <strong className="text-[#000000]">Workflow</strong> giải thích cấu trúc hệ thống và vai trò của các workflow trong khóa luận.
              </li>
              <li>
                <strong className="text-[#000000]">Leaderboard</strong> so sánh kết quả giữa các Workflow trên cùng mốc thời gian.
              </li>
              <li>
                <strong className="text-[#000000]">Trading View</strong> nối hành động giao dịch với dữ liệu giá và dấu mốc thực thi.
              </li>
              <li>
                <strong className="text-[#000000]">Báo cáo</strong> hiển thị các đầu ra mô tả theo ngày giải thích.
              </li>
            </ul>
          </div>
        </section>

        <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {[
            {
              label: "Best Return",
              value: `${bestReturn >= 0 ? "+" : ""}${bestReturn.toFixed(2)}%`,
              tone: "text-[#10A37F]",
              sub: "Mốc tốt nhất theo Workflow",
              surface: "bg-[#FFFFFF]",
            },
            {
              label: "Top Sharpe",
              value: topSharpe.toFixed(2),
              tone: "text-[#FF6B35]",
              sub: "Hiệu quả điều chỉnh theo rủi ro",
              surface: "bg-[#F9F9F9]",
            },
            {
              label: "Max Drawdown",
              value: `${maxDD.toFixed(1)}%`,
              tone: "text-[#EF4444]",
              sub: "Mức giảm sâu nhất",
              surface: "bg-[#F9F9F9]",
            },
            {
              label: "Tracked Workflows",
              value: 4,
              tone: "text-[#000000]",
              sub: "Số Workflow khả dụng",
              surface: "bg-[#F5F5F5]",
            },
          ].map((kpi) => (
            <div key={kpi.label} className={`pixel-border p-6 md:p-7 ${kpi.surface}`}>
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">{kpi.label}</div>
              <div className={`${vt323.className} mt-4 text-5xl uppercase tracking-[0.06em] ${kpi.tone}`}>
                {kpi.value}
              </div>
              <div className="mt-3 text-[11px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                {kpi.sub}
              </div>
            </div>
          ))}
        </section>

        <section className="grid gap-8 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="space-y-6">
            <div>
              <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
                Cấu trúc
              </div>
              <h2 className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
                Các điểm chính
              </h2>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {[
                {
                  href: "/agents",
                  title: "Workflow",
                  text: "Giải thích các Workflow chính, vai trò thành phần và luồng thông tin của hệ thống.",
                  surface: "bg-[#F9F9F9]",
                },
                {
                  href: "/leaderboard",
                  title: "Leaderboard",
                  text: "So sánh kết quả giữa các Workflow trên cùng một mốc backtest.",
                  surface: "bg-[#FFFFFF]",
                },
                {
                  href: "/trading-view",
                  title: "Trading View",
                  text: "Kiểm tra dữ liệu giá và các dấu mốc hành động của từng Workflow theo mã cổ phiếu.",
                  surface: "bg-[#F5F5F5]",
                },
                {
                  href: "/blogs",
                  title: "Báo cáo",
                  text: "Đọc các báo cáo theo ngày để hiểu ngữ cảnh phân tích và quyết định đã lưu.",
                  surface: "bg-[#F9F9F9]",
                },
              ].map((item) => (
                <Link
                  key={item.title}
                  href={item.href}
                  className={`pixel-border p-5 md:p-6 transition-colors hover:-translate-y-[2px] hover:border-[#FAAD14] ${item.surface}`}
                >
                  <div className={`${vt323.className} text-3xl uppercase tracking-[0.08em] text-[#000000]`}>
                    {item.title}
                  </div>
                  <p className="mt-3 text-sm leading-6 text-[#666666]">{item.text}</p>
                </Link>
              ))}
            </div>
          </div>

          <div className="pixel-border bg-[#FFFFFF] p-8 md:p-9">
            <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
            </div>
            <h2 className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
              Ghi chú
            </h2>
            <div className="mt-5 space-y-4 text-sm leading-7 text-[#666666]">
              <p>
                Đây không phải là giao diện giao dịch trực tiếp. Đây là các giao dịch thực hiện trên sàn ảo với dữ liệu được lưu từ trước và được trình bày lại để phân tích và đánh giá.
              </p>
              <p>
                Giao diện được thiết kế để giúp giảng viên và hội đồng hiểu hệ thống đang làm gì, các Workflow khác nhau ra sao và những bằng chứng nào đã có sẵn trong repository.
              </p>
              <p>
                Thanh timeline cho phép phát lại tiến trình backtest theo thời gian, để toàn bộ dashboard được đọc như một nghiên cứu có thể xem lại thay vì một website tĩnh.
              </p>
            </div>
            <div className="mt-6 border border-border-light bg-[var(--surface-tint)] px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-text-secondary font-mono">
              Số báo cáo khả dụng: {posts.length} · Số Workflow: {summaries.length}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
