import os
import mplfinance as mpf
from .market_tool import MarketToolkit

class ChartToolkit:
    # Lưu vào thư mục static để sau này Streamlit hiển thị
    CHART_DIR = "static/charts"
    
    @staticmethod
    def generate_candle_chart(symbol: str) -> str:
        """Vẽ biểu đồ nến và trả về đường dẫn file ảnh."""
        if not os.path.exists(ChartToolkit.CHART_DIR):
            os.makedirs(ChartToolkit.CHART_DIR)
            
        # Gọi hàm mới get_price_data
        df = MarketToolkit.get_price_data(symbol, days=180)
        
        if df.empty: 
            return "Lỗi: Không có dữ liệu để vẽ biểu đồ."
        
        try:
            # Định dạng lại index cho mplfinance
            df = df.set_index('date')
            
            # Style chuyên nghiệp
            mc = mpf.make_marketcolors(up='green', down='red', edge='inherit', wick='inherit', volume='in')
            s = mpf.make_mpf_style(marketcolors=mc, gridstyle=':', y_on_right=True)
            
            filename = f"{symbol}_chart.png"
            filepath = os.path.join(ChartToolkit.CHART_DIR, filename)
            
            # Vẽ biểu đồ
            mpf.plot(
                df, 
                type='candle', 
                mav=(20, 50), 
                volume=True, 
                title=f"{symbol} - Daily Chart (6 Months)",
                style=s, 
                savefig=dict(fname=filepath, dpi=100, bbox_inches='tight'),
                tight_layout=True,
                figratio=(12, 6),
                figscale=1.0
            )
            return filepath
            
        except Exception as e:
            return f"Lỗi vẽ biểu đồ: {e}"