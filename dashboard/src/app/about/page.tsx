import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

export default function AboutPage() {
  return (
    <div className="w-full px-4 py-14 md:px-8 md:py-16">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-14">
        <section className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.28em] text-text-secondary font-mono">
              Tổng quan khóa luận
            </div>
            <h1 className={`${vt323.className} text-6xl uppercase tracking-[0.08em] text-[#000000] md:text-7xl`}>
              Giới thiệu dự án
            </h1>
            <p className="max-w-4xl text-sm leading-8 text-[#666666] md:text-[15px]">
              TradingAgent-VN là dashboard trình bày cho một dự án khóa luận AI về phân tích và ra quyết định đầu tư mô phỏng trên thị trường chứng khoán Việt Nam. Hệ thống kết hợp dữ liệu giá, tin tức, ngữ cảnh tài chính, kiểm soát rủi ro và các Workflow phân tích để tạo thành một môi trường nghiên cứu có thể giải thích và có thể kiểm tra lại.
            </p>
          </div>
          <div className="pixel-border bg-[var(--surface-tint)] p-6 md:p-7">
            <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
              Luận điểm chính
            </div>
            <p className="mt-3 text-sm leading-6 text-[#666666]">
              Trọng tâm khóa luận là tìm cách sử dụng hệ thống multi-agent để giải quyết các vấn đề mang tính chất lặp lại và khó giải quyết đối với nhà đầu tư cá nhân và tối ưu hệ thống multi-agent sao cho hiệu quả nhất.
            </p>
          </div>
        </section>

        <section className="grid gap-8 lg:grid-cols-[1fr_1fr]">
          <article className="pixel-border bg-[#FFFFFF] p-8 md:p-9">
            <div className="text-[10px] uppercase tracking-[0.22em] text-text-secondary font-mono">
              Bài toán và phạm vi
            </div>
            <h2 className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
              Hệ thống đang giải quyết điều gì
            </h2>
            <div className="mt-5 space-y-4 text-sm leading-7 text-[#666666]">
              <p>
                Quyết định của nhà đầu tư chịu ảnh hưởng đồng thời bởi nhiều nguồn thông tin: dữ liệu giá, biến động kỹ thuật, tin tức, bối cảnh doanh nghiệp và trạng thái danh mục. Dự án này nghiên cứu cách tổ chức những nguồn đó thành một quy trình AI có cấu trúc thay vì phụ thuộc vào một tín hiệu đơn lẻ.
              </p>
              <p>
                Hệ thống được xây dựng như một môi trường backtest và nghiên cứu, không phải nền tảng giao dịch thực tế. Giá trị của nó nằm ở khả năng mô phỏng, giải thích, lưu vết và đánh giá.
              </p>
            </div>
          </article>

          <article className="pixel-border bg-[#F9F9F9] p-8 md:p-9">
            <div className="text-[10px] uppercase tracking-[0.22em] text-text-secondary font-mono">
              Cấu trúc Workflow
            </div>
            <h2 className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
              Dự án được tổ chức ra sao
            </h2>
            <div className="mt-5 space-y-4 text-sm leading-7 text-[#666666]">
              <p>
                Bối cảnh khóa luận  hiện có cả Workflow Cognitive Trading Traditional, Kelly và Markowitz. Trong bối cảnh khóa luận, các Workflow Traditional, Kelly, Markowitz được hiểu như các chiến thuật đầu tư phổ biến hiện nay.
              </p>
              <p>
                Các thành phần phụ bao gồm cơ sở dữ liệu tin tức được crawl từ CafeF từ ngày 01/01/2025 tới 30/03/2026 thông qua tracking_news mcp tool (thuộc phạm vi của khóa luận), dữ liệu báo cáo tài chính, dữ liệu giá cổ phiếu và các chỉ số được lấy từ  vnstock api. Các dữ liệu trên được thu thập, lưu trữ để phục vụ quá trình backtest của hệ thống.
              </p>
            </div>
          </article>
        </section>

        <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
          {[
            {
              title: "Dữ liệu đầu vào",
              text: "Dữ liệu thị trường, dữ liệu tin tức và ngữ cảnh tài chính được đưa vào các Workflow theo cấu trúc đã định.",
              surface: "bg-[#FFFFFF]",
            },
            {
              title: "Quy trình quyết định",
              text: "Các Workflow chuyển đổi bằng chứng thành hành động thông qua debate, tối ưu hóa hoặc tổng hợp.",
              surface: "bg-[#F9F9F9]",
            },
            {
              title: "Kiểm soát rủi ro",
              text: "Các quy tắc thực thi cứng ngăn lớp phân tích vượt qua ràng buộc danh mục và thị trường.",
              surface: "bg-[#F9F9F9]",
            },
            {
              title: "Artifact đầu ra",
              text: "Báo cáo, ledger, workflow summaries và file phân tích giúp hệ thống dễ trình bày và truy vết.",
              surface: "bg-[#F5F5F5]",
            },
          ].map((item) => (
            <article key={item.title} className={`pixel-border p-6 md:p-7 ${item.surface}`}>
              <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">Khía cạnh của dự án</div>
              <h3 className={`${vt323.className} mt-2 text-3xl uppercase tracking-[0.08em] text-[#000000]`}>
                {item.title}
              </h3>
              <p className="mt-4 text-sm leading-6 text-[#666666]">{item.text}</p>
            </article>
          ))}
        </section>

        <section className="pixel-border bg-[#FFFFFF] p-8 md:p-10">
          <div className="text-[10px] uppercase tracking-[0.22em] text-text-secondary font-mono">
            Tóm tắt kỹ thuật và trình bày
          </div>
          <h2 className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
            Tại sao sử dụng dashboard này
          </h2>
          <div className="mt-6 grid gap-6 md:grid-cols-2">
            <div className="border border-border-light bg-[var(--surface-tint)] p-5 md:p-6">
              <div className="text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">Bề mặt kỹ thuật</div>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-[#666666]">
                <li>• Dashboard Next.js phục vụ giải thích và kiểm tra</li>
                <li>• Hệ backtest Python cho orchestration của Workflow</li>
                <li>• SQLite cho artifact cục bộ và dữ liệu thị trường</li>
                <li>• LLM được đặt trong ràng buộc Workflow và governance</li>
              </ul>
            </div>
            <div className="border border-border-light bg-[var(--surface-warm)] p-5 md:p-6">
              <div className="text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">Ghi chú trình bày</div>
              <p className="mt-3 text-sm leading-6 text-[#666666]">
                Dashboard này được dùng như công cụ bảo vệ luận điểm: nó giúp trình bày sự khác biệt giữa các Workflow, kiểm tra artifact đã lưu và nối các chỉ số báo cáo với tiến trình backtest. Bản thân dashboard không phải là bằng chứng khoa học duy nhất, mà là lớp trình bày cho bằng chứng đã có trong bối cảnh dự án.
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
