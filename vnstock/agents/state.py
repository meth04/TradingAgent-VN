from typing import TypedDict, Optional

class AgentState(TypedDict):
    ticker: str
    ref_date: str
    
    price_data: Optional[str]   # Giá & Chỉ báo kỹ thuật
    news_data: Optional[str]    # Tin tức doanh nghiệp
    macro_data: Optional[str]   # Tin vĩ mô
    quant_data: Optional[str]   # Dự báo XGBoost
    
    # Kết quả phân tích (Output của Agents)
    macro_analysis: str
    fundamental_analysis: str   # Lấy từ Cache
    technical_analysis: str
    quant_analysis: str
    news_analysis: str
    
    final_signal: str           # BUY/SELL/HOLD
    report_content: str         # Bài báo cáo tổng hợp