import sys
from config import models
from vnstock.agents.prompting import BACKTEST_CONTEXT, TEXT_COT_PREFIX
from vnstock.core.llm import call_llm
from vnstock.tools.search_tool import SearchToolkit


class MacroAgent:
    async def analyze(self, *, ref_date: str) -> str:
        print("🌐 [Macro Agent] Đang phân tích dòng tiền vĩ mô (Async)...", file=sys.stderr)

        raw_news = await SearchToolkit.search_macro(ref_date=ref_date, limit=6)

        system_prompt = (
            f"{BACKTEST_CONTEXT} "
            f"{TEXT_COT_PREFIX} "
            "Hãy suy luận từng bước bằng tiếng Việt. Trước hết đánh giá dữ liệu vĩ mô gốc; "
            "sau đó liệt kê ĐÚNG 3 Pros có thể kiểm chứng; tiếp theo liệt kê ĐÚNG 3 Cons "
            "có thể kiểm chứng; chỉ xuất ra các nhận định chuyên gia. "
            "Bạn là Chuyên gia Chiến lược Vĩ mô tại hedge fund."
        )
        user_prompt = f"""
        Ngày phân tích (ref_date): {ref_date}. Coi đây là ngày hiện tại.

        Phân tích bối cảnh vĩ mô Việt Nam dựa trên tin tức:
        {raw_news}

        NHIỆM VỤ (giữ đúng thứ tự):
        1) Đánh giá dữ liệu nguồn.
        2) Liệt kê 3 Pros có dẫn chứng rõ nguồn.
        3) Liệt kê 3 Cons có dẫn chứng rõ nguồn.

        OUTPUT (ngắn gọn, sạch, có bằng chứng):
        - Pros: 3 gạch đầu dòng, kèm nguồn.
        - Cons: 3 gạch đầu dòng, kèm nguồn.
        - **Dòng tiền & Lãi suất:** SBV đang nới lỏng hay thắt chặt? Lãi suất liên ngân hàng thế nào?
        - **Tỷ giá & Ngoại khối:** Áp lực tỷ giá USD/VND tác động ra sao đến dòng vốn ngoại?
        - **Sentiment:** Tích cực / Tiêu cực / Thận trọng.
        - Kết luận cuối cùng phải có dòng: `Dự đoán ảnh hưởng: [+/- X%]` (ví dụ `Dự đoán ảnh hưởng: -2.0%`).
        """

        try:
            result = await call_llm(
                system_prompt,
                user_prompt,
                model=models.t2_macro_model,
                temperature=0.4,
            )
        except Exception:
            result = str(raw_news)
        if "<thinking>" not in result:
            print("[Macro Agent] ⚠️ Missing <thinking> tag in response", file=sys.stderr)
        if "Dự đoán ảnh hưởng" not in result:
            result = result.rstrip() + "\n\nDự đoán ảnh hưởng: +0%"
        return result
