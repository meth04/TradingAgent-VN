"use client";

import { useMemo, useEffect, useState } from "react";
import { VT323 } from "next/font/google";

const vt323 = VT323({ weight: "400", subsets: ["latin"], variable: "--font-vt323" });

type WorkflowConfig = {
  label: string;
  positioning: string;
  summary: string;
  informationFlow: string[];
  focus: string[];
  architecture: string;
  components: { name: string; role: string; desc: string }[];
};

const WORKFLOW_CONFIGS: Record<string, WorkflowConfig> = {
  Traditional: {
    label: "Baseline Traditional",
    positioning: "Workflow baseline kế thừa",
    summary:
      "Traditional là Workflow kế thừa trực tiếp và dễ đọc nhất. Nó tổng hợp phân tích đa nguồn, đi qua một bước debate đơn giản, rồi chuyển sang tầng quyết định cuối cùng. Trong câu chuyện khóa luận, đây nên được xem là baseline để so sánh thay vì là đóng góp trung tâm.",
    informationFlow: [
      "Thu thập bằng chứng từ dữ liệu giá, tin tức và ngữ cảnh tài chính cho từng mã tại từng ngày.",
      "Tổng hợp lập luận tích cực và tiêu cực trong một bước debate đơn giản.",
      "Tầng quyết định cuối cùng chọn hành động và mức phân bổ sơ bộ.",
      "Danh mục và risk rules quyết định liệu lệnh đó có thể được thực thi hay không.",
    ],
    focus: [
      "Khả năng làm baseline để so sánh",
      "Luồng quyết định dễ giải thích",
      "Độ phức tạp thấp hơn rõ rệt so với Cognitive Trading",
    ],
    architecture: "Dữ liệu đầu vào → phân tích dùng chung → debate summary → CIO decision → portfolio execution",
    components: [
      {
        name: "Shared analysis layer",
        role: "Lớp thu thập bằng chứng",
        desc: "Tập hợp cùng một họ tín hiệu dùng trong các Workflow kế thừa để giúp việc so sánh giữa chiến lược trở nên nhất quán.",
      },
      {
        name: "Debate stage",
        role: "Bộ lọc lập luận",
        desc: "Làm rõ các luận điểm bullish và bearish trước khi chọn hành động cuối cùng.",
      },
      {
        name: "Decision layer",
        role: "Tầng chọn hành động",
        desc: "Chuyển phần tóm tắt bằng chứng thành hành động giao dịch và phân bổ sơ bộ.",
      },
    ],
  },
  Kelly: {
    label: "Baseline Kelly",
    positioning: "Workflow baseline thiên về Position Sizing",
    summary:
      "Kelly vẫn đi theo cấu trúc kế thừa nhưng chú trọng mạnh hơn vào Position Sizing. Thay vì chỉ hỏi có nên giao dịch hay không, nó còn hỏi nên đi vốn mạnh đến đâu. Trong khóa luận, đây là baseline phù hợp để so sánh ở góc độ phân bổ vốn.",
    informationFlow: [
      "Thu thập cùng một nhóm tín hiệu thị trường và ngữ cảnh như các Workflow kế thừa khác.",
      "Ước lượng mức độ tin cậy và lợi thế kỳ vọng từ tập tín hiệu đang có.",
      "Đề xuất một weight cho giao dịch theo logic Kelly-style.",
      "Portfolio và risk rules xác định liệu mức phân bổ đó có hợp lệ trong mô phỏng hay không.",
    ],
    focus: [
      "Kỷ luật Position Sizing",
      "Phân bổ vốn dựa trên xác suất và lợi thế",
      "Baseline quan trọng để so sánh với chất lượng quyết định của Cognitive Trading",
    ],
    architecture: "Dữ liệu đầu vào → tổng hợp phân tích → ước lượng edge và confidence → Kelly sizing → portfolio execution",
    components: [
      {
        name: "Analysis synthesis",
        role: "Bộ kết hợp tín hiệu",
        desc: "Gom các tín hiệu kỹ thuật, định lượng và ngữ cảnh thành một decision context duy nhất.",
      },
      {
        name: "Kelly sizing logic",
        role: "Tầng điều tiết phân bổ",
        desc: "Chuyển bài toán từ chọn hành động nhị phân sang xác định mức phân bổ vốn hợp lý hơn.",
      },
      {
        name: "Execution controls",
        role: "Tầng chặn thực thi",
        desc: "Ngăn một vị thế hấp dẫn về mặt toán học vượt qua các ràng buộc danh mục trong thực tế mô phỏng.",
      },
    ],
  },
  Markowitz: {
    label: "Baseline Markowitz",
    positioning: "Workflow baseline thiên về tối ưu hóa danh mục",
    summary:
      "Markowitz hoạt động ở cấp độ danh mục thay vì chỉ ở cấp từng mã riêng lẻ. Nó sử dụng cùng họ bằng chứng đầu vào nhưng chuyển bài toán thành một vấn đề phân bổ danh mục. Trong khóa luận, nó là baseline quan trọng để so sánh góc nhìn portfolio-level với Cognitive Trading.",
    informationFlow: [
      "Thu thập danh sách candidate và bằng chứng liên quan trên nhiều mã cổ phiếu.",
      "Đánh giá mối quan hệ danh mục thay vì chỉ conviction ở từng mã riêng lẻ.",
      "Bộ tối ưu hóa đề xuất một phân bổ rổ danh mục.",
      "Phân bổ cuối cùng vẫn bị kiểm tra lại bởi các ràng buộc thực thi và danh mục.",
    ],
    focus: [
      "Portfolio construction",
      "Phân bổ có tính đến đa dạng hóa",
      "Baseline mạnh để so với Workflow Cognitive ở cấp độ danh mục",
    ],
    architecture: "Shared evidence → candidate basket → optimization step → CIO validation → portfolio execution",
    components: [
      {
        name: "Candidate basket stage",
        role: "Tầng chuẩn bị đầu vào danh mục",
        desc: "Tập hợp các ý tưởng giao dịch trước khi chuyển thành bài toán phân bổ toàn rổ.",
      },
      {
        name: "Optimization stage",
        role: "Bộ tối ưu hóa phân bổ",
        desc: "Cân bằng giữa kỳ vọng lợi nhuận và rủi ro danh mục trên nhiều mã.",
      },
      {
        name: "Validation stage",
        role: "Kiểm tra tính khả thi",
        desc: "Đảm bảo phân bổ tối ưu vẫn tuân theo giới hạn thực thi của danh mục mô phỏng.",
      },
    ],
  },
  Cognitive: {
    label: "Cognitive Trading",
    positioning: "Hệ thống multi agent tự nhận thức và cải thiện quyết định đầu tư",
    summary:
      "Cognitive Trading là hướng giải quyết tối ưu nhất của khóa luận. Đây không chỉ là một biến thể chiến lược khác, mà là một hệ thống ra quyết định đa tác tử có cấu trúc, kết hợp deterministic planning, role-based analysts, schema validation, optional debate, CIO synthesis, deterministic risk controls và post-run memory/reflection. Đây là Workflow thể hiện rõ nhất đóng góp của đề tài.",
    informationFlow: [
      "Một event ledger an toàn theo ref_date được xây dựng từ dữ liệu thị trường, tin tức và các tín hiệu ngữ cảnh.",
      "Context theo từng mã được đóng gói thành các view có cấu trúc cho các analyst chuyên biệt.",
      "Các analyst theo vai trò tạo ra analysis cards có kiểu dữ liệu rõ ràng và được validate, calibrate trước khi dùng tiếp.",
      "Nếu tín hiệu xung đột, hệ thống kích hoạt debate trước khi đưa ra tổng hợp cuối cùng.",
      "Tầng CIO chuyển toàn bộ bằng chứng thành intent, sau đó deterministic risk kernel quyết định lệnh có được thông qua hay không.",
      "Kết quả thực thi được ghi lại vào daily artifacts, episodic memory, lịch sử calibration và reflection outputs.",
    ],
    focus: [
      "Suy luận đa tác tử có thể giải thích",
      "Governance có cấu trúc quanh đầu ra của LLM",
      "Kiểm soát thực thi cứng quanh lớp phân tích mang tính xác suất",
      "Memory và reflection như một phần nghiên cứu thực sự, không chỉ là yếu tố trang trí",
    ],
    architecture:
      "Event ledger → context packing → analyst swarm → schema/governance → conditional debate → CIO decision → risk kernel → portfolio execution → memory and reflection",
    components: [
      {
        name: "Event ledger",
        role: "Bộ dựng ngữ cảnh an toàn theo thời gian",
        desc: "Chụp lại trạng thái thị trường tại một ngày giao dịch cụ thể và giúp hạn chế nguy cơ nhìn thấy dữ liệu tương lai.",
      },
      {
        name: "Context packer",
        role: "Lớp đóng gói đầu vào",
        desc: "Biến dữ liệu thô thành các context rõ ràng hơn: giá, tin tức, macro, financial và portfolio.",
      },
      {
        name: "Analyst swarm",
        role: "Lớp suy luận chuyên biệt",
        desc: "Chạy các analyst theo vai trò như macro, technical, quant, news và financial trên cùng một tập bằng chứng đã bị chặn bởi ref_date.",
      },
      {
        name: "Schema và calibration layer",
        role: "Lớp governance",
        desc: "Ép đầu ra analyst vào các card có cấu trúc và calibrate confidence trước khi dùng ở các tầng dưới.",
      },
      {
        name: "Debate và CIO synthesis",
        role: "Giải quyết xung đột và tổng hợp cuối cùng",
        desc: "Đẩy các trường hợp bất đồng sang debate rồi chuyển cho CIO để sinh ra intent cuối cùng.",
      },
      {
        name: "Risk kernel",
        role: "Cổng thực thi deterministic",
        desc: "Áp dụng các ràng buộc cứng của danh mục và thị trường để đảm bảo hành động cuối cùng vẫn tuân thủ luật mô phỏng.",
      },
      {
        name: "Memory và reflection",
        role: "Lớp học tập và quy kết kết quả",
        desc: "Lưu trade episodes, cập nhật calibration và tạo reflection artifacts cho các lần đánh giá sau.",
      },
    ],
  },
};

type AnalysisCard = {
  agent_name: string;
  action: string;
  confidence_calibrated: number;
  reasoning: string;
  _thought_process?: string[];
};

type AnalysisResponse = {
  _mock?: boolean;
  message?: string;
  ledger_data?: {
    action?: string;
    target_weight_pct?: number;
    net_score?: number;
  };
  cards?: AnalysisCard[];
  cio?: {
    action: string;
    reasoning: string;
    weight_pct: number;
  };
};

const workflowOrder = ["Cognitive", "Traditional", "Kelly", "Markowitz"];

function normalizeWorkflowQuery(value: string) {
  const lower = value.trim().toLowerCase();
  if (lower.includes("traditional")) return "Traditional";
  if (lower.includes("kelly")) return "Kelly";
  if (lower.includes("markowitz")) return "Markowitz";
  if (lower.includes("cognitive")) return "Cognitive";
  return "Cognitive";
}

function stripThinkTags(value: string | null | undefined) {
  return (value || "")
    .replace(/<(think|thinking)>[\s\S]*?<\/(think|thinking)>/gi, "")
    .replace(/<\/?(think|thinking)>/gi, "")
    .replace(/&lt;(think|thinking)&gt;[\s\S]*?&lt;\/(think|thinking)&gt;/gi, "")
    .replace(/&lt;\/?(think|thinking)&gt;/gi, "")
    .trim();
}

function sanitizeThoughtProcess(steps: string[] | undefined) {
  return (steps || []).reduce<string[]>((acc, step) => {
    const cleaned = stripThinkTags(step);
    if (cleaned) acc.push(cleaned);
    return acc;
  }, []);
}

export function AgentsClient({
  analysisDates,
}: {
  analysisDates: string[];
}) {
  const initialWorkflow = useMemo(() => {
    if (typeof window === "undefined") return "Cognitive";
    const params = new URLSearchParams(window.location.search);
    const workflowParam = params.get("workflow");
    return workflowParam ? normalizeWorkflowQuery(workflowParam) : "Cognitive";
  }, []);

  const [selectedWorkflow, setSelectedWorkflow] = useState<string>(initialWorkflow);
  const [selectedDate, setSelectedDate] = useState<string>(analysisDates[analysisDates.length - 1] || "");
  const [selectedTicker, setSelectedTicker] = useState<string>("FPT");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [tickers, setTickers] = useState<string[]>([]);

  const workflowData = WORKFLOW_CONFIGS[selectedWorkflow as keyof typeof WORKFLOW_CONFIGS];

  useEffect(() => {
    fetch("/api/tickers")
      .then((res) => res.json())
      .then((data) => setTickers(data));
  }, []);

  useEffect(() => {
    if (selectedDate && selectedTicker) {
      fetch(
        "/api/analysis?date=" +
          selectedDate +
          "&ticker=" +
          selectedTicker +
          "&workflow=" +
          selectedWorkflow.toLowerCase()
      )
        .then((res) => res.json())
        .then((data: AnalysisResponse) => setAnalysis(data))
        .catch(() => setAnalysis(null));
    }
  }, [selectedDate, selectedTicker, selectedWorkflow]);

  return (
    <div className="w-full bg-bg-primary px-4 py-14 text-text-primary md:px-8 md:py-16">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-14">
        <section className="grid gap-8 lg:grid-cols-[1.2fr_0.8fr] lg:items-start">
          <div className="space-y-5">
            <div className="text-[10px] uppercase tracking-[0.32em] text-text-secondary font-mono">
              Tổng quan Workflow
            </div>
            <h1 className={`${vt323.className} text-5xl uppercase leading-none tracking-[0.08em] text-[#000000] md:text-6xl`}>
              Chi tiết Workflow của hệ thống
            </h1>
            <p className="max-w-3xl text-sm leading-8 text-[#666666] md:text-[15px]">
            </p>
          </div>

          <div className="pixel-border bg-[var(--surface-warm)] p-6 md:p-7">
            <div className="text-[10px] uppercase tracking-[0.22em] text-text-secondary font-mono">
              Hướng dẫn
            </div>
            <ul className="mt-4 space-y-3 text-sm leading-6 text-[#666666]">
              <li>
                Bắt đầu từ Traditional, Kelly, Markowitz để hiểu vấn đề chính của bài toán.
              </li>
              <li>
                Nghiên cứu kỹ Cognitive để hiểu hướng giải quyết.
              </li>
              <li>
                Dùng phần bên dưới để kiểm tra artifact đã lưu theo ngày và theo ticker.
              </li>
            </ul>
          </div>
        </section>

        <section className="grid gap-8 xl:grid-cols-[0.92fr_1.08fr]">
          <div className="space-y-4">
            <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
              Chọn Workflow
            </div>
            <div className="grid gap-4">
              {workflowOrder.map((workflow, index) => {
                const active = workflow === selectedWorkflow;
                const config = WORKFLOW_CONFIGS[workflow];
                return (
                  <button
                    key={workflow}
                    type="button"
                    onClick={() => setSelectedWorkflow(workflow)}
                    className={`pixel-border w-full px-5 py-5 text-left transition-colors ${
                      active
                        ? "bg-[#F5F5F5] border-[#8B5CF6]"
                        : index % 2 === 0
                          ? "bg-[#FFFFFF] hover:border-[#FAAD14]"
                          : "bg-[#F9F9F9] hover:border-[#FAAD14]"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className={`${vt323.className} text-2xl uppercase tracking-[0.08em] text-[#000000]`}>
                          {workflow}
                        </div>
                        <div className="mt-1 text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                          {config.positioning}
                        </div>
                      </div>
                      {active ? (
                        <span className="border border-[#8B5CF6] bg-[#8B5CF6] px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-white font-mono">
                          Đang chọn
                        </span>
                      ) : null}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="pixel-border bg-[#FFFFFF] p-7 md:p-8">
            <div className="flex flex-wrap items-center gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
                  Workflow hiện tại
                </div>
                <h2 className={`${vt323.className} text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
                  {selectedWorkflow}
                </h2>
              </div>
              <span className="border border-border bg-[var(--surface-tint)] px-3 py-1 text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                {workflowData.label}
              </span>
            </div>

            <p className="mt-5 text-sm leading-8 text-[#666666] md:text-[15px]">{workflowData.summary}</p>

            <div className="mt-7 grid gap-5 lg:grid-cols-2">
              <div className="border border-border-light bg-[#FFFFFF] p-5">
                <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                  Tóm tắt kiến trúc
                </div>
                <p className="mt-3 text-sm leading-6 text-[#000000]">{workflowData.architecture}</p>
              </div>
              <div className="border border-border-light bg-[var(--surface-warm)] p-5">
                <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                  Vì sao Workflow này quan trọng
                </div>
                <ul className="mt-3 space-y-2 text-sm leading-6 text-[#666666]">
                  {workflowData.focus.map((item) => (
                    <li key={item}>• {item}</li>
                  ))}
                </ul>
              </div>
            </div>
          </div>
        </section>

        <section className="grid gap-8 lg:grid-cols-[1fr_1.1fr]">
          <div className="pixel-border bg-[#FFFFFF] p-7 md:p-8">
            <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
              Luồng thông tin
            </div>
            <ol className="mt-5 space-y-4">
              {workflowData.informationFlow.map((step, index) => (
                <li key={step} className="flex gap-4 border-l-2 border-[#FF6B35] pl-4">
                  <div className={`${vt323.className} text-3xl leading-none text-[#FF6B35]`}>{index + 1}</div>
                  <p className="text-sm leading-6 text-[#666666]">{step}</p>
                </li>
              ))}
            </ol>
          </div>

          <div className="space-y-4">
            <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
              Thành phần và vai trò
            </div>
            <div className="grid gap-4">
              {workflowData.components.map((component, index) => (
                <div key={component.name} className={`pixel-border p-5 ${index % 2 === 0 ? "bg-[#FFFFFF]" : "bg-[#F9F9F9]"}`}>
                  <div className="flex flex-col gap-1 md:flex-row md:items-baseline md:justify-between">
                    <h3 className={`${vt323.className} text-2xl uppercase tracking-[0.06em] text-[#000000]`}>
                      {component.name}
                    </h3>
                    <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                      {component.role}
                    </div>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-[#666666]">{component.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="pixel-border bg-[#FFFFFF] p-7 md:p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-3">
              <div className="text-[10px] uppercase tracking-[0.24em] text-text-secondary font-mono">
                Kiểm tra artifact theo ngày
              </div>
              <h2 className={`${vt323.className} text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
                Xem các đầu ra đã lưu
              </h2>
              <p className="max-w-3xl text-sm leading-6 text-[#666666]">
                Các bộ chọn dưới đây giữ nguyên cách dashboard đang nạp dữ liệu. Chúng cho phép xem artifact theo Workflow, ngày và ticker mà không làm thay đổi cơ chế đọc dữ liệu hiện có.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Workflow
                <select
                  value={selectedWorkflow}
                  onChange={(e) => setSelectedWorkflow(e.target.value)}
                  className="border-2 border-border bg-[#FFFFFF] px-3 py-3 text-sm text-[#000000] outline-none"
                >
                  {Object.keys(WORKFLOW_CONFIGS).map((wf) => (
                    <option key={wf} value={wf}>
                      {wf}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Ngày phân tích
                <select
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="border-2 border-border bg-[#FFFFFF] px-3 py-3 text-sm text-[#000000] outline-none"
                >
                  {analysisDates.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                Ticker
                <select
                  value={selectedTicker}
                  onChange={(e) => setSelectedTicker(e.target.value)}
                  className="border-2 border-border bg-[#FFFFFF] px-3 py-3 text-sm text-[#000000] outline-none"
                >
                  {tickers.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </div>

          <div className="mt-6 border border-border-light bg-[var(--surface-tint)] px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-text-secondary font-mono">
            Đang xem: {selectedWorkflow} / {selectedTicker} / {selectedDate || "Chưa có ngày"}
          </div>

          {analysis && analysis._mock ? (
            <div className="mt-6 border-2 border-border-light bg-[#FFFFFF] p-8 text-center">
              <h3 className={`${vt323.className} text-3xl uppercase tracking-[0.08em] text-[#000000]`}>
                Chưa có artifact chi tiết
              </h3>
              <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-[#666666]">{analysis.message}</p>
              {analysis.ledger_data ? (
                <div className="mx-auto mt-6 max-w-xl border border-border-light bg-[var(--surface-tint)] p-5 text-left text-sm text-[#666666]">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                    Ngữ cảnh ledger hiện có
                  </div>
                  <div className="mt-3 space-y-2 font-mono text-[12px]">
                    <div>Action: {analysis.ledger_data.action}</div>
                    {analysis.ledger_data.target_weight_pct ? (
                      <div>Target weight: {analysis.ledger_data.target_weight_pct}%</div>
                    ) : null}
                    {analysis.ledger_data.net_score ? <div>Net score: {analysis.ledger_data.net_score}</div> : null}
                  </div>
                </div>
              ) : null}
            </div>
          ) : analysis && (analysis.cards || analysis.cio) ? (
            <div className="mt-6 space-y-6">
              {analysis.cards?.length ? (
                <div>
                  <div className="mb-3 text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                    Analysis cards
                  </div>
                  <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                    {analysis.cards.map((card, i: number) => {
                      const reasoning = stripThinkTags(card.reasoning);
                      const thoughtProcess = sanitizeThoughtProcess(card._thought_process);

                      return (
                        <article key={i} className="pixel-border bg-[#FFFFFF] p-5">
                          <div className="flex items-start justify-between gap-4 border-b border-border-light pb-4">
                            <div>
                              <h3 className={`${vt323.className} text-2xl uppercase tracking-[0.06em] text-[#000000]`}>
                                {card.agent_name}
                              </h3>
                              <div className="text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                                Đầu ra analyst đã chuẩn hóa
                              </div>
                            </div>
                            <div className="border border-border bg-[var(--surface-tint)] px-2 py-1 text-[10px] uppercase tracking-[0.12em] font-mono text-[#000000]">
                              {card.action} · {card.confidence_calibrated}%
                            </div>
                          </div>
                          <p className="mt-4 text-sm leading-6 text-[#666666]">{reasoning}</p>
                          {thoughtProcess.length ? (
                            <div className="mt-5 border-t border-border-light pt-4">
                              <div className="text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                                Trace
                              </div>
                              <div className="mt-2 space-y-2">
                                {thoughtProcess.map((step: string, j: number) => (
                                  <div key={j} className="font-mono text-[12px] text-[#666666]">
                                    &gt; {step}
                                  </div>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              {analysis.cio ? (
                <section className="pixel-border bg-[#F9F9F9] p-6 md:p-8">
                  <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
                    <div className="max-w-3xl">
                      <div className="text-[10px] uppercase tracking-[0.18em] text-text-secondary font-mono">
                        Tổng hợp cuối cùng
                      </div>
                      <h3 className={`${vt323.className} mt-2 text-4xl uppercase tracking-[0.08em] text-[#000000]`}>
                        CIO decision
                      </h3>
                      <p className="mt-4 text-sm leading-7 text-[#666666]">{stripThinkTags(analysis.cio.reasoning)}</p>
                    </div>
                    <div className="border-2 border-border bg-[#FFFFFF] p-5 min-w-[220px]">
                      <div className="text-[10px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                        Hành động thực thi
                      </div>
                      <div className={`${vt323.className} mt-2 text-5xl uppercase tracking-[0.08em] text-[#000000]`}>
                        {analysis.cio.action}
                      </div>
                      <div className="mt-4 text-[11px] uppercase tracking-[0.16em] text-text-secondary font-mono">
                        Phân bổ mục tiêu: {analysis.cio.weight_pct}%
                      </div>
                    </div>
                  </div>
                </section>
              ) : null}
            </div>
          ) : (
            <div className="mt-6 border-2 border-border-light bg-[#FFFFFF] p-10 text-center">
              <h3 className={`${vt323.className} text-3xl uppercase tracking-[0.08em] text-[#000000]`}>
                Chưa có artifact cho lựa chọn này
              </h3>
              <p className="mx-auto mt-4 max-w-2xl text-sm leading-6 text-[#666666]">
                Trường hợp này thường có nghĩa là chưa tồn tại artifact đã lưu cho tổ hợp Workflow, ngày và ticker đang được chọn.
              </p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
