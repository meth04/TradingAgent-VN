import asyncio
import os
import sys

from dotenv import load_dotenv

# --- CHẶN STDOUT ---
class StderrPrinter:
    def write(self, message):
        sys.stderr.write(message)

    def flush(self):
        sys.stderr.flush()

original_stdout = sys.stdout
sys.stdout = StderrPrinter()

# --- SETUP PATH ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

load_dotenv(os.path.join(project_root, ".env"))

def debug_log(*args):
    print(*args, file=sys.stderr)

try:
    from mcp.server.fastmcp import FastMCP
    from vnstock.tools.search_tool import SearchToolkit
    from vnstock.tools.market_tool import MarketToolkit
    from vnstock.tools.quant_tool import QuantToolkit
    from vnstock.agents.financial_analysis import DynamicFinancialAgent, FinancialAnalysisError
except ImportError as e:
    debug_log(f"CRITICAL ERROR: {e}")
    sys.exit(1)

mcp = FastMCP("Vietnam Financial Core")

# --- 1. NHÓM I/O BOUND (Đã là Async -> Gọi trực tiếp) ---

@mcp.tool()
async def get_macro_news() -> str:
    # SearchToolkit giờ là async, nên await trực tiếp
    return await SearchToolkit.search_macro(limit=5)

@mcp.tool()
async def get_stock_news(ticker: str) -> str:
    return await SearchToolkit.search_news(f"Tin tức sự kiện {ticker}", limit=5)

# --- 2. NHÓM CPU BOUND (Chưa Async -> Dùng Thread) ---

@mcp.tool()
async def get_technical_report(ticker: str) -> str:
    # Pandas chạy nặng -> đẩy vào Thread
    return await asyncio.to_thread(MarketToolkit.get_technical_report, ticker)

@mcp.tool()
async def get_price_history(ticker: str, days: int = 30) -> str:
    df = await asyncio.to_thread(MarketToolkit.get_price_data, ticker, days)
    if df.empty:
        return "No Data"
    return df.tail(days).to_csv(index=False)

@mcp.tool()
async def run_quant_prediction(ticker: str) -> str:
    debug_log(f"📡 Server: Chạy Quant Ranking {ticker}...")
    
    def _run_quant():
        tool = QuantToolkit()
        if not tool.features:
            tool.train_model()

        result = tool.get_market_ranking()
        if "error" in result:
            return f"❌ Lỗi Quant: {result['error']}"

        target_info = "Neutral"
        score = 50.0
        # Logic filter cho ticker...
        for item in result.get("top_strong_buy", []):
            if item['ticker'] == ticker:
                target_info = "STRONG BUY"
                score = item['confidence']
                break

        return f"""
        ### 🤖 DỰ BÁO ĐỊNH LƯỢNG
        - **Mã:** {ticker}
        - **Xếp hạng:** {target_info}
        - **Điểm:** {score:.1f}
        """

    # Quant train model rất nặng -> đẩy vào Thread
    return await asyncio.to_thread(_run_quant)

@mcp.tool()
async def analyze_financial_report(ticker: str, year: str, quarter: str) -> str:
    debug_log(f"📡 Server: Phân tích BCTC {ticker}...")
    agent = DynamicFinancialAgent(ticker, year, quarter)
    try:
        return await agent.analyze()
    except FinancialAnalysisError as exc:
        return f"❌ Lỗi phân tích tài chính: {exc}"

if __name__ == "__main__":
    debug_log("🚀 Server Ready...")
    sys.stdout = original_stdout
    mcp.run()