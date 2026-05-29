import sys
import os
import asyncio

# --- FIX ĐƯỜNG DẪN (Path Hack) ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.append(project_root)

# Import các tools
try:
    from vnstock.tools.search_tool import SearchToolkit
    from vnstock.tools.market_tool import MarketToolkit
    from vnstock.tools.chart_tool import ChartToolkit
    from vnstock.tools.quant_tool import QuantToolkit

    try:
        from vnstock.tools.rag_tool import FinancialRAGTool
        _ = FinancialRAGTool
    except ImportError:
        print("⚠️ Module RAG chưa sẵn sàng (Bỏ qua test RAG).")

except ImportError as e:
    print(f"❌ Lỗi Import: {e}")
    sys.exit(1)

def print_header(title):
    print(f"\n{'='*60}\n TESTING: {title}\n{'='*60}")

async def main():
    ticker = "HPG" # Mã cổ phiếu test: Hòa Phát

    # 1. TEST SEARCH
    print_header("SEARCH TOOLKIT (Serper API)")
    try:
        # Lưu ý: Hàm search_news nhận 2 tham số: query và limit
        news = SearchToolkit.search_news(f"Tin tức {ticker}", limit=2)
        print(f"✅ Kết quả Search:\n{news[:300]}...\n(Đã cắt ngắn)")
    except Exception as e:
        print(f"❌ Lỗi Search: {e}")
    
    # 2. TEST MARKET DATA
    print_header("MARKET TOOLKIT (Real Data)")
    try:
        # GỌI HÀM MỚI: get_technical_report
        tech_report = MarketToolkit.get_technical_report(ticker)
        print(f"✅ Báo cáo Kỹ thuật:\n{tech_report}")
    except Exception as e:
        print(f"❌ Lỗi Market Data: {e}")

    # 3. TEST CHARTING
    print_header("CHART TOOLKIT")
    try:
        chart_path = ChartToolkit.generate_candle_chart(ticker)
        print(f"✅ Biểu đồ đã lưu tại: {chart_path}")
    except Exception as e:
        print(f"❌ Lỗi Charting: {e}")

    # 4. TEST QUANT MODEL
    print_header("QUANT TOOLKIT (XGBoost Real-time Training)")
    try:
        # Tool này sẽ tự tải data -> tự train -> tự predict
        prediction = QuantToolkit.get_prediction(ticker)
        print(f"✅ Kết quả Dự báo AI:\n{prediction}")
    except Exception as e:
        print(f"❌ Lỗi Quant: {e}")

if __name__ == "__main__":
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())