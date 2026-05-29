import asyncio
import sys
from typing import Dict

from config import models
from vnstock.agents.prompting import BACKTEST_CONTEXT, TEXT_COT_PREFIX
from vnstock.core.llm import call_llm


class QuantAgent:
    async def analyze(self, *, ticker: str, ref_date: str) -> str:
        print(f"🤖 [Quant Agent] Tính Alpha cho {ticker} @ {ref_date}...")

        def _run_quant() -> Dict[str, float] | str:
            # Ensure external vnstock package path precedes shadowed project name
            from pathlib import Path
            import importlib

            sp = Path(__file__).resolve().parents[2] / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
            if sp.is_dir() and str(sp) not in sys.path:
                sys.path.insert(0, str(sp))
            try:
                importlib.import_module("vnstock")
            except Exception:
                pass

            from vnstock.tools.quant_tool import QuantToolkit

            tool = QuantToolkit()
            try:
                report = tool.quick_report(ticker, ref_date)
            except Exception as exc:  # pylint: disable=broad-except
                tool.close()
                return f"❌ Lỗi Quant: {exc}"
            tool.close()
            return report

        result = await asyncio.to_thread(_run_quant)
        if isinstance(result, str):
            return result

        system_prompt = (
            f"{BACKTEST_CONTEXT} "
            f"{TEXT_COT_PREFIX} "
            "Hãy suy luận từng bước bằng tiếng Việt. Trước hết đánh giá các factor định lượng gốc; "
            "sau đó liệt kê ĐÚNG 3 Pros có thể kiểm chứng; tiếp theo liệt kê ĐÚNG 3 Cons "
            "có thể kiểm chứng; chỉ xuất ra các nhận định chuyên gia."
        )
        user_prompt = (
            f"Ngày phân tích (ref_date): {ref_date}. Coi đây là ngày hiện tại.\n\n"
            "### 🤖 ĐỊNH LƯỢNG ALPHA (Institutional Blend)\n"
            f"- Mã: {ticker}\n"
            f"- Alpha Score: {result['alpha_score']:.2f} (0-100)\n"
            "- Thành phần:\n"
            f"  - Momentum (30%): EMA20={result['ema20']:.2f}, EMA50={result['ema50']:.2f}, RSI14={result['rsi14']:.2f}\n"
            f"  - Dòng tiền ngoại 5d (20%): {result['foreign_flow_5d']:.2f}\n"
            f"  - AI Sentiment 30d (20%): {result['sentiment_score']:.2f} (conf={result['sentiment_conf']:.2f})\n"
            f"  - Value (15%): PE={result.get('pe')}, PB={result.get('pb')}, score={result.get('value_score', 0.0):.2f}\n"
            f"  - Quality (15%): ROE={result.get('roe')}, ROA={result.get('roa')}, score={result.get('quality_score', 0.0):.2f}\n"
            f"- ATR14 (volatility for sizing): {result['atr14']:.4f}\n"
            "- Pros: 3 gạch đầu dòng, kèm dữ liệu.\n"
            "- Cons: 3 gạch đầu dòng, kèm dữ liệu.\n"
            "- Gợi ý sizing: nhỏ khi ATR cao; tăng dần khi ATR giảm và alpha > 60.\n"
            f"- Dự đoán ảnh hưởng: +{result.get('alpha_score', 50.0):.1f}% (ước lượng)\n"
        )

        llm_result = await call_llm(
            system_prompt,
            user_prompt,
            model=models.t2_quant_model,
            
        )

        if "<thinking>" not in llm_result:
            print("[Quant Agent] ⚠️ Missing <thinking> tag in response", file=sys.stderr)
        return llm_result


