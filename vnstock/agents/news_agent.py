import sys
from config import models
from vnstock.agents.prompting import BACKTEST_CONTEXT, TEXT_COT_PREFIX
from vnstock.core.llm import call_llm
from vnstock.tools.search_tool import SearchToolkit

class NewsAgent:
    async def analyze(self, *, ticker: str, ref_date: str) -> str:
        print(f"📰 [News Agent] Đang lọc tin đồn & sự kiện {ticker}...", file=sys.stderr)

        raw_news = await SearchToolkit.search_news(
            f"Tin tức sự kiện {ticker}", ref_date=ref_date, ticker=ticker, limit=5
        )

        system_prompt = (
            f"{BACKTEST_CONTEXT} "
            f"{TEXT_COT_PREFIX} "
            "Hãy suy luận từng bước bằng tiếng Việt. Trước hết đánh giá dữ liệu tin tức gốc; "
            "sau đó liệt kê ĐÚNG 3 Pros có thể kiểm chứng; tiếp theo liệt kê ĐÚNG 3 Cons "
            "có thể kiểm chứng; chỉ xuất ra các nhận định chuyên gia. "
            "Bạn là Chuyên gia Phân tích Sự kiện."
        )
        user_prompt = f"""
        Ngày phân tích (ref_date): {ref_date}. Coi đây là ngày hiện tại.

        Phân tích tin tức cho {ticker}:
        {raw_news}

        NHIỆM VỤ (giữ đúng thứ tự):
        1) Đánh giá dữ liệu nguồn.
        2) Liệt kê 3 Pros có dẫn chứng rõ nguồn.
        3) Liệt kê 3 Cons có dẫn chứng rõ nguồn.

        OUTPUT (ngắn gọn, có bằng chứng):
        - Pros: 3 gạch đầu dòng, kèm nguồn.
        - Cons: 3 gạch đầu dòng, kèm nguồn.
        - Phân loại tin: (Tin Lợi nhuận / M&A / Lãnh đạo / Vĩ mô ngành / Tin đồn).
        - Đánh giá tác động: Ngắn hạn (T+3) vs Dài hạn.
        - Sentiment Score: Thang 1-10.
        - Kết luận cuối cùng phải có dòng: `Dự đoán ảnh hưởng: [+/- X%]` (ví dụ `Dự đoán ảnh hưởng: +3.5%`).
        """

        result = await call_llm(
            system_prompt,
            user_prompt,
            model=models.t2_news_model,
            
        )
        if "<thinking>" not in result:
            print("[News Agent] ⚠️ Missing <thinking> tag in response", file=sys.stderr)
        if "Dự đoán ảnh hưởng" not in result:
            result = result.rstrip() + "\n\nDự đoán ảnh hưởng: +0%"
        return result

