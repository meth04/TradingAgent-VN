import sys
import asyncio
from config import models
from vnstock.agents.prompting import BACKTEST_CONTEXT, TEXT_COT_PREFIX
from vnstock.core.llm import call_llm

class TechnicalAgent:
    async def analyze(self, *, ticker: str, ref_date: str) -> str:
        print(f"📈 [Technical Agent] Đang soi chart {ticker}...", file=sys.stderr)

        # Lazy import: tránh block startup bằng heavy deps (pandas, numpy...)
        def _get_report():
            from vnstock.tools.market_tool import MarketToolkit
            return MarketToolkit.get_technical_report(ticker, ref_date=ref_date)

        tech_data = await asyncio.to_thread(_get_report)

        system_prompt = (
            f"{BACKTEST_CONTEXT} "
            f"{TEXT_COT_PREFIX} "
            "Hãy suy luận từng bước bằng tiếng Việt. Trước hết đánh giá dữ liệu kỹ thuật gốc; "
            "sau đó liệt kê ĐÚNG 3 Pros có thể kiểm chứng; tiếp theo liệt kê ĐÚNG 3 Cons "
            "có thể kiểm chứng; chỉ xuất ra các nhận định chuyên gia. "
            "Bạn là trader chuyên nghiệp theo trường phái Price Action và hợp lưu chỉ báo."
        )
        user_prompt = f"""
        Ngày phân tích (ref_date): {ref_date}. Coi đây là ngày hiện tại.

        Phân tích kỹ thuật mã {ticker} dựa trên dữ liệu:
        {tech_data}

        NHIỆM VỤ (giữ đúng thứ tự):
        1) Đánh giá dữ liệu nguồn.
        2) Liệt kê 3 Pros có dẫn chứng rõ.
        3) Liệt kê 3 Cons có dẫn chứng rõ.

        YÊU CẦU:
        - **Cấu trúc thị trường:** Giá đang ở Phase nào (Tích lũy, Tăng trưởng, Phân phối, Đè giá)?
        - **Sự hợp lưu (Confluence):** Các chỉ báo (RSI, MACD, Ichimoku, Volume) có đồng thuận không hay mâu thuẫn?
        - **Setup Giao dịch:** Entry, Stoploss, Take Profit.
        - Kết luận cuối cùng phải có dòng: `Dự đoán ảnh hưởng: [+/- X%]` (ví dụ `Dự đoán ảnh hưởng: +4.0%`).
        """

        result = await call_llm(
            system_prompt,
            user_prompt,
            model=models.t2_technical_model,
            
        )
        if "<thinking>" not in result:
            print("[Technical Agent] ⚠️ Missing <thinking> tag in response", file=sys.stderr)
        if "Dự đoán ảnh hưởng" not in result:
            result = result.rstrip() + "\n\nDự đoán ảnh hưởng: +0%"
        return result


