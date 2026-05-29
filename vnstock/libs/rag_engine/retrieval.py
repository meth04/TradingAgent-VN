import os
import asyncio
import re
import sys
from datetime import datetime

from lightrag import QueryParam

from .config import settings
from .core import get_rag_engine
from .llm import openai_complete_if_cache


async def _run_with_timeout(coro: asyncio.Future, timeout_seconds: float, label: str):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{label} vượt quá {timeout_seconds:.0f}s") from exc

# Danh sách 30 mã VN30 chính xác
VN30_MAPPING = {
    "ACB": ["ACB", "Á CHÂU"], "BCM": ["BCM", "BECAMEX"], "BID": ["BID", "BIDV", "ĐẦU TƯ VÀ PHÁT TRIỂN"],
    "CTG": ["CTG", "VIETINBANK", "CÔNG THƯƠNG"], "DGC": ["DGC", "ĐỨC GIANG"], "FPT": ["FPT"],
    "GAS": ["GAS", "PV GAS"], "GVR": ["GVR", "CAO SU"], "HDB": ["HDB", "HDBANK"],
    "HPG": ["HPG", "HÒA PHÁT"], "LPB": ["LPB", "LPBANK", "LỘC PHÁT", 'LP Bank'], "MBB": ["MBB", "MB BANK", "QUÂN ĐỘI"],
    "MSN": ["MSN", "MASAN"], "MWG": ["MWG", "THẾ GIỚI DI ĐỘNG"], "PLX": ["PLX", "PETROLIMEX"],
    "SAB": ["SAB", "SABECO"], "SHB": ["SHB"], "SSB": ["SSB", "SEABANK"], "SSI": ["SSI"],
    "STB": ["STB", "SACOMBANK"], "TCB": ["TCB", "TECHCOMBANK"], "TPB": ["TPB", "TPBANK", "TIÊN PHONG"],
    "VCB": ["VCB", "VIETCOMBANK", "NGOẠI THƯƠNG"], "VHM": ["VHM", "VINHOMES"], "VIB": ["VIB"],
    "VIC": ["VIC", "VINGROUP"], "VJC": ["VJC", "VIETJET"], "VNM": ["VNM", "VINAMILK"],
    "VPB": ["VPB", "VPBANK"], "VRE": ["VRE", "VINCOM RETAIL"]
}

FINANCIAL_CODE_MAPPING = {
    # Bảng Cân đối kế toán
    "TỔNG TÀI SẢN": ["Mã số 270", "Tổng tài sản"],
    "TIỀN": ["Mã số 110", "Tiền và các khoản tương đương tiền"],
    "ĐẦU TƯ TÀI CHÍNH": ["Mã số 120", "Mã số 250"],
    "PHẢI THU": ["Mã số 130", "Mã số 210"],
    "HÀNG TỒN KHO": ["Mã số 140", "Hàng tồn kho"],
    "TÀI SẢN CỐ ĐỊNH": ["Mã số 220"],
    "NỢ PHẢI TRẢ": ["Mã số 300", "Tổng nợ phải trả"],
    "VAY": ["Mã số 320", "Mã số 338", "Vay và nợ thuê tài chính"],
    "VỐN CHỦ SỞ HỮU": ["Mã số 400", "Mã số 410"],
    
    # Kết quả kinh doanh (Doanh nghiệp)
    "DOANH THU": ["Mã số 01", "Mã số 10", "Doanh thu thuần"],
    "GIÁ VỐN": ["Mã số 11", "Giá vốn hàng bán"],
    "LỢI NHUẬN GỘP": ["Mã số 20"],
    "DOANH THU TÀI CHÍNH": ["Mã số 21"],
    "CHI PHÍ TÀI CHÍNH": ["Mã số 22"],
    "CHI PHÍ BÁN HÀNG": ["Mã số 25"],
    "CHI PHÍ QUẢN LÝ": ["Mã số 26"],
    "LỢI NHUẬN THUẦN": ["Mã số 30"],
    "LỢI NHUẬN TRƯỚC THUẾ": ["Mã số 50", "Tổng lợi nhuận kế toán trước thuế"],
    "LỢI NHUẬN SAU THUẾ": ["Mã số 60", "Lợi nhuận sau thuế thu nhập doanh nghiệp"],
    
    # Kết quả kinh doanh (Ngân hàng - Đặc thù)
    "THU NHẬP LÃI THUẦN": ["Thu nhập lãi thuần", "I. Thu nhập lãi thuần"],
    "LÃI THUẦN DỊCH VỤ": ["Lãi thuần từ hoạt động dịch vụ"],
    "DỰ PHÒNG RỦI RO": ["Chi phí dự phòng rủi ro tín dụng"],
    
    # Lưu chuyển tiền tệ
    "LƯU CHUYỂN TIỀN TỪ HĐKD": [
    "Mã số 20", 
    "Lưu chuyển tiền thuần từ hoạt động kinh doanh", 
    "Dòng tiền thuần từ hoạt động kinh doanh"
    ],
    "LƯU CHUYỂN TIỀN TỪ ĐẦU TƯ": ["Mã số 30", "Lưu chuyển tiền thuần từ hoạt động đầu tư"],
    "LƯU CHUYỂN TIỀN TỪ TÀI CHÍNH": ["Mã số 40", "Lưu chuyển tiền thuần từ hoạt động tài chính"],

}

def get_financial_hints_and_report_type(question):
    """
    Trả về: (Danh sách mã số gợi ý, Loại báo cáo cần tìm)
    """
    q_upper = question.upper()
    hints = []
    report_type = ""

    # Xác định loại báo cáo để khoanh vùng tìm kiếm
    if any(x in q_upper for x in ["TÀI SẢN", "NỢ", "VỐN", "VAY", "TIỀN GỬI"]):
        report_type = "Bảng cân đối kế toán"
    elif any(x in q_upper for x in ["LỢI NHUẬN", "DOANH THU", "LÃI", "CHI PHÍ"]):
        report_type = "Báo cáo kết quả hoạt động kinh doanh"
    elif any(x in q_upper for x in ["LƯU CHUYỂN", "DÒNG TIỀN", "TIỀN THU", "TIỀN CHI"]):
        report_type = "Báo cáo lưu chuyển tiền tệ"

    # Lấy mã số
    for key, codes in FINANCIAL_CODE_MAPPING.items():
        # Check kỹ hơn: key phải nằm trọn vẹn trong câu hỏi hoặc các từ khóa chính khớp
        if key in q_upper:
            hints.extend(codes)
        # Fallback cho trường hợp viết tắt: "LCTT" -> Lưu chuyển tiền tệ
        if "LCTT" in q_upper and "LƯU CHUYỂN" in key:
            hints.extend(codes)

    return list(set(hints))[:4], report_type


def identify_ticker_python_fallback(question):
    q_upper = question.upper()
    for ticker, keywords in VN30_MAPPING.items():
        if any(kw in q_upper for kw in keywords):
            return ticker
    return None

def remove_think_tag(text):
    """Loại bỏ nội dung trong thẻ <think> để lấy đáp án cuối cùng"""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

async def extract_metadata_smart(question):
    """
    Kết hợp Python (nhận diện Tên công ty) + LLM (suy luận Thời gian).
    """
    now = datetime.now()
    current_date_str = now.strftime("%d/%m/%Y")
    
    detected_ticker = identify_ticker_python_fallback(question)
    
    ticker_hint = f"Đã phát hiện mã: {detected_ticker}" if detected_ticker else "Chưa xác định được mã, hãy tự suy luận từ tên công ty."

    mapping_str = "\n".join([f"- {k}: {', '.join(v)}" for k, v in VN30_MAPPING.items()])

    prompt = f"""
    Bạn là bộ định tuyến metadata cho hệ thống Financial RAG tiếng Việt.

    NHIỆM VỤ:
    Từ câu hỏi người dùng, xác định chính xác:
    1) Mã cổ phiếu (Ticker)
    2) Năm báo cáo
    3) Quý báo cáo

    THỜI GIAN HIỆN TẠI: {current_date_str}

    DANH SÁCH MAPPING (MÃ : TÊN PHỔ BIẾN):
    {mapping_str}

    CÂU HỎI NGƯỜI DÙNG:
    "{question}"

    HINT TICKER TỪ PYTHON:
    {ticker_hint}

    NGUYÊN TẮC BẮT BUỘC:

    A. XÁC ĐỊNH TICKER
    - Nếu HINT đã có ticker hợp lệ thì ưu tiên dùng ticker đó.
    - Nếu HINT chưa có, suy luận ticker từ tên doanh nghiệp, tên thương hiệu, tên viết tắt hoặc mã cổ phiếu trong câu hỏi.
    - Chỉ được chọn ticker nằm trong danh sách mapping ở trên.
    - Nếu câu hỏi nhắc nhiều doanh nghiệp, chọn doanh nghiệp là đối tượng chính của câu hỏi.
    - Không tự tạo ticker ngoài danh sách.

    B. XÁC ĐỊNH KỲ BÁO CÁO
    - Nếu câu hỏi nêu rõ quý/năm, dùng đúng quý/năm đó.
    - Nếu câu hỏi chỉ nêu năm mà không nêu quý, mặc định là Q4 của năm đó.
    - Nếu câu hỏi dùng thời gian tương đối như "quý trước", "năm ngoái", "quý gần nhất", phải suy luận dựa trên THỜI GIAN HIỆN TẠI.
    - Nếu câu hỏi nêu một ngày cụ thể:
    + Tháng 1-3 => Q1
    + Tháng 4-6 => Q2
    + Tháng 7-9 => Q3
    + Tháng 10-12 => Q4
    - Nếu câu hỏi không nhắc thời gian:
    + Mặc định chọn quý gần nhất ĐÃ KẾT THÚC theo logic báo cáo tài chính.
    + Ví dụ: nếu hiện tại đang ở giữa Q2/2026 thì quý gần nhất đã kết thúc là Q1/2026.
    + Không chọn một quý chưa kết thúc.

    C. ƯU TIÊN TÍNH ỔN ĐỊNH
    - Không giải thích.
    - Không thêm chữ thừa.
    - Không dùng markdown.
    - Không trả JSON.
    - Không xuống dòng.

    D. ĐẦU RA DUY NHẤT
    Trả đúng 1 dòng theo format:
    TICKER|YEAR|QUARTER

    Ví dụ hợp lệ:
    ACB|2025|Q1
    VHM|2024|Q4
    FPT|2026|Q1
    """
    try:
        res = await openai_complete_if_cache(
            prompt, 
            model_name=settings.LLM_MODEL, 
            temperature=0.0,
            max_tokens=50
        )
        
        parts = res.strip().split('|')
        if len(parts) >= 3:
            ticker = parts[0].strip().upper()
            year = parts[1].strip()
            quarter = parts[2].strip().upper()
            
            if ticker not in VN30_MAPPING:
                fallback = identify_ticker_python_fallback(question)
                if fallback:
                    ticker = fallback
                else:
                    ticker = "DEFAULT"
                
            return ticker, year, quarter
            
    except Exception as e:
        print(f"[ROUTING ERROR] {e}", file=sys.stderr)

    # Fallback cuối cùng
    return "DEFAULT", "2025", "Q3"


def identify_ticker_python(question):
    q = question.upper()
    for ticker, keywords in VN30_MAPPING.items():
        if any(kw in q for kw in keywords):
            return ticker
    return "DEFAULT"

async def generate_search_queries(question: str, ticker: str, year: str, quarter: str):
    """
    Chiến lược sinh Query thế hệ 3: Multi-Industry & Deep Anchor.
    Bao phủ: Sản xuất, Ngân hàng, Bất động sản, Chứng khoán.
    """

    financial_hints, report_type = get_financial_hints_and_report_type(question)
    hint_str = ", ".join(financial_hints) if financial_hints else "Không có"
    report_type_hint = report_type if report_type else "Chưa xác định"

    time_period = f"{quarter}/{year}"
    
    # Prompt được thiết kế như một chuyên gia Kế toán trưởng (Chief Accountant)
    prompt = f"""
    Bạn là Financial Retrieval Planner cho hệ thống RAG đọc OCR báo cáo tài chính Việt Nam.

    MỤC TIÊU:
    Sinh ra đúng 5 truy vấn retrieval để tìm evidence tốt nhất cho câu hỏi.
    Các truy vấn phải giúp hệ thống tìm được:
    - đúng doanh nghiệp
    - đúng kỳ báo cáo
    - đúng loại báo cáo / thuyết minh
    - đúng chỉ tiêu hoặc các thành phần cấu thành chỉ tiêu
    - đúng cụm từ trong văn phong báo cáo tài chính Việt Nam

    INPUT:
    - Question: "{question}"
    - Ticker: {ticker}
    - Year: {year}
    - Quarter: {quarter}
    - Loại báo cáo gợi ý: {report_type_hint}
    - Financial hints / mã số / anchor: {hint_str}

    BẢN CHẤT NHIỆM VỤ:
    Không phải câu hỏi nào cũng nên truy đúng nguyên văn.
    Nếu câu hỏi là chỉ tiêu phân tích như NIM, ROA, ROE, CIR, chất lượng lợi nhuận, dòng tiền, đòn bẩy, coverage..., hãy sinh truy vấn để tìm CÁC THÀNH PHẦN CẤU THÀNH chứ không chỉ truy chữ khóa bề mặt.

    QUY TẮC THIẾT KẾ 5 TRUY VẤN:

    1. Query 1 = DIRECT LABEL QUERY
    - Truy vấn sát nhất với chỉ tiêu/cụm từ người dùng hỏi.
    - Phải chứa ticker + year.
    - Nếu có thể, chứa đúng loại báo cáo.

    2. Query 2 = FINANCIAL SYNONYM QUERY
    - Dùng từ đồng nghĩa/nhãn kế toán Việt Nam tương ứng.
    - Ví dụ:
    - doanh thu => doanh thu thuần
    - lợi nhuận => lợi nhuận sau thuế / tổng lợi nhuận kế toán trước thuế
    - CFO => lưu chuyển tiền thuần từ hoạt động kinh doanh
    - ngân hàng => thu nhập lãi thuần / chi phí lãi / chi phí dự phòng rủi ro tín dụng

    3. Query 3 = STATEMENT / NOTE ANCHOR QUERY
    - Khoanh đúng bảng hoặc thuyết minh.
    - Ví dụ:
    - Báo cáo kết quả hoạt động kinh doanh
    - Bảng cân đối kế toán
    - Báo cáo lưu chuyển tiền tệ
    - Thuyết minh báo cáo tài chính

    4. Query 4 = COMPONENT / DRIVER QUERY
    - Nếu câu hỏi là analytical hoặc derived, truy vấn các cấu phần chính để suy luận.
    - Ví dụ:
    - NIM => thu nhập lãi, chi phí lãi, tài sản sinh lãi
    - CASA => tiền gửi không kỳ hạn, tiền gửi khách hàng
    - ROE => lợi nhuận sau thuế, vốn chủ sở hữu
    - chất lượng lợi nhuận => lợi nhuận sau thuế, lưu chuyển tiền thuần từ hoạt động kinh doanh
    - hàng tồn kho => thuyết minh hàng tồn kho, dự phòng giảm giá hàng tồn kho
    - bất động sản => người mua trả tiền trước, hàng tồn kho, chi phí xây dựng cơ bản dở dang

    5. Query 5 = CODE / ANCHOR QUERY
    - Dùng mã số, tên dòng chuẩn, hoặc anchor tài chính mạnh nếu có.
    - Ưu tiên dùng financial hints đã cho.
    - Query này phải đặc biệt hữu ích với OCR bảng.

    QUY TẮC NGÀNH:
    - Ngân hàng:
    + Ưu tiên các cụm: Thu nhập lãi thuần, Chi phí lãi, Lãi thuần từ hoạt động dịch vụ, Chi phí dự phòng rủi ro tín dụng, Tiền gửi của khách hàng, Phát hành giấy tờ có giá.
    - Doanh nghiệp sản xuất / bán lẻ / tiêu dùng:
    + Ưu tiên: Doanh thu thuần, Giá vốn hàng bán, Lợi nhuận gộp, Hàng tồn kho, Phải thu, Nợ phải trả.
    - Bất động sản:
    + Ưu tiên: Người mua trả tiền trước, Hàng tồn kho, Chi phí xây dựng cơ bản dở dang, Thuyết minh dự án.
    - Chứng khoán:
    + Ưu tiên: Tài sản tài chính FVTPL, cho vay margin, doanh thu môi giới, lãi từ tài sản tài chính.

    RÀNG BUỘC CHẤT LƯỢNG:
    - Mỗi query một dòng.
    - Không đánh số.
    - Không markdown.
    - Không giải thích.
    - Không tạo câu quá dài.
    - Tất cả query phải có ticker và year.
    - Ít nhất 2 query phải chứa một cụm nhãn tài chính chuẩn.
    - Nếu có report_type_hint thì ít nhất 1 query phải chứa report_type_hint.
    - Nếu có financial hints thì cố gắng rải chúng vào query 4 hoặc query 5.

    ĐẦU RA:
    Trả đúng 5 dòng, mỗi dòng là 1 query.
    """

    try:
        res = await openai_complete_if_cache(prompt, model=settings.GPT_MODEL, temperature=0.1, max_tokens=1024)
        
        lines = [line.strip() for line in res.splitlines() if line.strip()]
        clean_queries = []
        for line in lines:
            clean_q = re.sub(r'^[\d\-\.\)\*]+\s+', '', line)
            if len(clean_q) > 5:
                clean_queries.append(clean_q)
        
        if not clean_queries:
            clean_queries = [
                f"{question} {year}",
                f"Báo cáo tài chính {ticker} {year}",
                f"Thuyết minh {question} {year}"
            ]
            
        return clean_queries[:5]

    except Exception as e:
        print(f"[Query Gen Error] {e}", file=sys.stderr)
        return [question, f"Báo cáo tài chính {ticker} {year}"]

async def refine_answer(question, raw_context):
    if len(raw_context) < 100: 
        return "Dữ liệu hiện không có trong báo cáo."

    # prompt = f"""
    # ROLE: Bạn là Chuyên gia Kiểm toán (Auditor) đang soát xét Báo cáo Tài chính tại Việt Nam.

    # Bạn PHẢI trả lời dựa CHỈ trên CONTEXT OCR bên dưới. Tuyệt đối không bịa/đoán.

    # ====================
    # CONTEXT (OCR):
    # {raw_context}
    # ====================

    # QUESTION:
    # {question}

    # QUY TẮC BẮT BUỘC (QUALITY GATES):
    # 1) KHÔNG ĐƯỢC BỊA SỐ:
    # - Mọi chữ số trong câu trả lời phải xuất hiện nguyên văn trong CONTEXT
    #     (ngoại lệ duy nhất xem mục "PHÉP TÍNH RẤT HẠN CHẾ").
    # - Nếu không tìm thấy số liệu đáp ứng đúng chỉ tiêu + đúng kỳ + đúng đơn vị -> phải trả lời "không có dữ liệu".

    # 2) KHỚP ĐÚNG CHỈ TIÊU (LABEL):
    # - Khi trả lời, PHẢI dùng đúng tên chỉ tiêu (Label) y hệt như trong CONTEXT (copy nguyên văn).
    # - Không được rút gọn/đổi tên chỉ tiêu theo cách của bạn.

    # 3) KHỚP ĐÚNG ĐỐI TƯỢNG:
    # - Nếu trong CONTEXT không có tên/ticker/ngữ cảnh nhận diện đúng công ty/ngân hàng được hỏi -> coi như không đủ dữ liệu.

    # 4) CHỌN ĐÚNG BẢNG & KỲ:
    # - "tại ngày / ngày dd/mm/yyyy" -> ưu tiên Bảng cân đối kế toán.
    # - "trong X tháng / lũy kế / 9 tháng / quý" -> ưu tiên Báo cáo KQKD hoặc LCTT tùy chỉ tiêu.
    # - Luôn chọn đúng cột thời gian tương ứng (kỳ này/kỳ trước; lũy kế/quý).

    # 5) ĐƠN VỊ:
    # - Giữ nguyên đơn vị tiền tệ đúng theo header của bảng (ví dụ: "triệu đồng", "tỷ đồng", "VND", "đồng").
    # - Không tự đổi đơn vị.

    # 6) BẪY LCTT:
    # - Với "Lưu chuyển tiền thuần từ hoạt động kinh doanh": nếu xuất hiện 2 lần, PHẢI chọn dòng tổng hợp cuối cùng (thường ở cuối mục, in đậm, gần các mục I/II/III).
    # - Không tự cộng/trừ để ra số LCTT.

    # 7) XUNG ĐỘT NHIỀU SỐ (CỰC QUAN TRỌNG):
    # Nếu có nhiều giá trị giống nhau/na ná cho cùng câu hỏi, áp dụng thứ tự ưu tiên:
    # (a) Dòng có LABEL khớp sát nhất với câu hỏi (ưu tiên trùng cụm từ chính).
    # (b) Dòng nằm trong bảng có "Mã số" / cấu trúc cột rõ ràng.
    # (c) Dòng có ngày/kỳ khớp chính xác với QUESTION.
    # Nếu sau ưu tiên (a)(b)(c) vẫn còn mơ hồ -> trả lời "không có dữ liệu" (để tránh chọn sai).

    # 8) QUY TẮC SỐ ÂM:
    # Trong báo cáo tài chính Việt Nam, các số âm được cho vào trong ngoặc như (398.631.979.587) VND, thì phải trả lời là -398.631.979.587 VND

    # CHUẨN HOÁ ĐỊNH DẠNG SỐ:
    # - Dùng dấu chấm (.) phân cách hàng nghìn: ví dụ 876.226.156
    # - Nếu OCR dùng dấu phẩy (,) như 876,226,156 thì hiểu là phân cách hàng nghìn và đổi thành 876.226.156
    # - KHÔNG được tự ý làm tròn.
    # - KHÔNG thêm dấu chấm ở cuối câu.
    # - SỐ ÂM:
    # - Nếu số trong CONTEXT ở dạng ngoặc (9.440.425) thì trả lời dạng -9.440.425
    # - Nếu số đã có dấu "-" thì giữ nguyên.

    # PHÉP TÍNH RẤT HẠN CHẾ (chỉ dùng khi đáp án KHÔNG có sẵn dưới dạng 1 dòng trong bảng):
    # - CHỈ được tính khi:
    # (1) QUESTION hỏi đúng chỉ tiêu "Lợi nhuận kế toán sau thuế thu nhập doanh nghiệp" hoặc "Lợi nhuận sau thuế"
    # (2) CONTEXT có đầy đủ 2 số cùng kỳ, cùng đơn vị:
    #     "Lợi nhuận kế toán trước thuế" và "Chi phí thuế thu nhập doanh nghiệp"
    # (3) Không có dòng "Lợi nhuận ... sau thuế" tương ứng trong CONTEXT
    # - Khi tính, phải ghi cực ngắn trong cùng câu: "(tính từ A - B)" và A/B phải là số có trong CONTEXT.
    # - Ngoài trường hợp này: TUYỆT ĐỐI KHÔNG TÍNH TOÁN.

    # YÊU CẦU TRẢ LỜI (OUTPUT):
    # - Chỉ trả lời 1 câu duy nhất, không xuống dòng, không bullet, không "giải thích", không "tham chiếu", không ký hiệu [1].
    # - Mẫu khi CÓ số:
    # "<LABEL> của <đối tượng như trong QUESTION> <kỳ trong QUESTION> là/đạt <SỐ> <ĐƠN VỊ>"
    # - Mẫu khi KHÔNG CÓ số:
    # "<chỉ tiêu trong QUESTION> của <đối tượng trong QUESTION> <kỳ trong QUESTION> hiện không có trong báo cáo"
    # """

    prompt = f"""
    Bạn là chuyên gia phân tích báo cáo tài chính Việt Nam, kết hợp tư duy kiểm toán, phân tích cơ bản và kiểm soát chất lượng bằng chứng.

    NHIỆM VỤ:
    Trả lời câu hỏi CHỈ dựa trên CONTEXT đã được truy xuất từ hệ thống.
    Không được bịa số. Không được suy diễn vượt quá evidence.
    Tuy nhiên, bạn được phép:
    - tổng hợp nhiều evidence cùng lúc,
    - suy luận ở mức vừa phải khi evidence đủ rõ,
    - nêu rõ giới hạn dữ liệu khi evidence chưa đủ.

    ====================
    CONTEXT:
    {raw_context}
    ====================

    QUESTION:
    {question}

    TRƯỚC KHI TRẢ LỜI, HÃY TỰ PHÂN LOẠI CÂU HỎI THÀNH 1 TRONG 3 NHÓM:

    1. EXTRACTIVE
    - Câu hỏi đòi một số liệu, một chỉ tiêu, một dòng trong bảng, hoặc một fact có thể đọc trực tiếp.

    2. DERIVED
    - Câu hỏi cần ghép 2-4 fact có sẵn trong context để kết luận hoặc tính toán đơn giản.
    - Ví dụ: so sánh tăng/giảm, dòng tiền có lệch lợi nhuận không, coverage có cao không, tỷ trọng có đáng chú ý không.

    3. ANALYTICAL
    - Câu hỏi yêu cầu đánh giá, giải thích driver, chất lượng lợi nhuận, độ bền vững, rủi ro, sensitivity, hoặc kết luận đầu tư.
    - Chỉ được trả lời analytical khi context có evidence thực sự hỗ trợ.
    - Nếu context chỉ có số liệu kế toán thô nhưng không đủ để kết luận nguyên nhân hay triển vọng, phải nói rõ “chưa đủ bằng chứng từ báo cáo/quý hiện tại”.

    NGUYÊN TẮC BẮT BUỘC:

    A. KHÔNG BỊA SỐ
    - Mọi con số nêu ra phải xuất hiện trong context, hoặc là kết quả của phép tính đơn giản từ các số có trong context.
    - Không dùng kiến thức ngoài context.
    - Không nêu peer comparison, định giá, market share, chiến lược, management commentary nếu context không có.

    B. ƯU TIÊN ĐÚNG LABEL
    - Khi trích dẫn chỉ tiêu, ưu tiên dùng đúng tên dòng / cụm từ trong context.
    - Không đổi nghĩa của nhãn tài chính.

    C. CHỌN ĐÚNG KỲ VÀ ĐÚNG BẢNG
    - Nếu câu hỏi hỏi “tại ngày”, ưu tiên bảng cân đối.
    - Nếu hỏi “trong kỳ”, “quý”, “lũy kế”, ưu tiên KQKD hoặc LCTT.
    - Nếu có nhiều kỳ trong context, chọn kỳ khớp nhất với question.

    D. PHÉP TÍNH CHO PHÉP
    - Được phép thực hiện các phép tính đơn giản khi cần và khi đủ số liệu:
    + cộng / trừ
    + tỷ lệ đơn giản
    + so sánh tăng/giảm
    + đối chiếu lợi nhuận với CFO
    - Không được dựng mô hình hoặc ước tính nếu context không đủ.

    E. QUY TẮC VỚI CÂU HỎI ANALYTICAL
    - Chỉ kết luận mạnh khi evidence trực tiếp hỗ trợ.
    - Nếu chỉ có thể kết luận một phần, phải nói rõ phần nào kết luận được và phần nào chưa đủ bằng chứng.
    - Nếu câu hỏi hỏi “vì sao”, “do đâu”, “bền vững không”, “có đáng lo không”, hãy:
    1) nêu kết luận ngắn,
    2) nêu evidence tài chính chính,
    3) nêu giới hạn bằng chứng nếu có.

    F. QUY TẮC SỐ ÂM VÀ ĐỊNH DẠNG
    - Nếu số âm trong ngoặc, chuyển sang dấu trừ.
    - Giữ nguyên đơn vị.
    - Không tự làm tròn nếu không cần.
    - Không đổi đơn vị.

    G. XỬ LÝ THIẾU DỮ LIỆU
    - Không dùng câu cứng nhắc kiểu “hiện không có trong báo cáo” cho mọi trường hợp.
    - Phải phân biệt:
    1) không tìm thấy chỉ tiêu,
    2) có số liệu nhưng chưa đủ để kết luận analytical,
    3) có thể kết luận một phần.

    FORMAT ĐẦU RA:
    Viết ngắn gọn nhưng chuyên nghiệp, tối đa 4 câu.
    Không markdown.
    Không bullet.
    Không giải thích lan man.

    MẪU PHONG CÁCH:
    - Với EXTRACTIVE:
    "<chỉ tiêu> của <doanh nghiệp/kỳ> là ...; số liệu này được ghi nhận tại ..."
    - Với DERIVED:
    "<kết luận ngắn>. Cơ sở là ... và ...; do đó có thể thấy ..."
    - Với ANALYTICAL:
    "<kết luận ngắn>. Evidence chính gồm ... và .... Tuy nhiên, báo cáo hiện tại chưa đủ bằng chứng để kết luận sâu hơn về ..."

    YÊU CẦU CUỐI:
    - Ưu tiên tính đúng hơn là nói hay.
    - Nếu evidence yếu, phải hạ độ chắc chắn của kết luận.
    - Không được nói quá.
    """

    response = await openai_complete_if_cache(
        prompt, 
        model_name=settings.REASONER_MODEL, 
        temperature=0.05,
        max_tokens=8192 
    )
    
    final_ans = remove_think_tag(response)
    
    return final_ans

async def query_func(placeholder, question: str, mode: str, ticker: str = None, year: str = None, quarter: str = None):
    # Nếu không truyền metadata, mới dùng LLM để suy luận (Smart Routing)
    if not all([ticker, year, quarter]):
        ticker, year, quarter = await extract_metadata_smart(question)
    
    print(f"\n>>> RAG ROUTING: {ticker} | {quarter}/{year}", file=sys.stderr) 
    
    rag = get_rag_engine(ticker, year, quarter)
    
    if not os.path.exists(rag.working_dir):
        return "", f"Xin lỗi, hiện tại hệ thống chưa có dữ liệu báo cáo của {ticker} vào {quarter}/{year}."

    await _run_with_timeout(
        rag.initialize_storages(),
        timeout_seconds=settings.STORAGE_INIT_TIMEOUT_SECONDS,
        label=f"khởi tạo RAG storage cho {ticker} {quarter}/{year}",
    )

    search_list = [question]
    expanded = await generate_search_queries(question, ticker, year, quarter)
    search_list.extend(expanded)

    tasks = [
        _run_with_timeout(
            rag.aquery(q, param=QueryParam(mode=mode, top_k=50)),
            timeout_seconds=settings.QUERY_TIMEOUT_SECONDS,
            label=f"truy vấn RAG `{q[:60]}`",
        )
        for q in search_list
    ]
    responses = await asyncio.gather(*tasks, return_exceptions=True)

    for response in responses:
        if isinstance(response, Exception):
            print(f"[RAG QUERY ERROR] {response}", file=sys.stderr)

    valid_contexts = [r for r in responses if isinstance(r, str) and len(r) > 200]

    MAX_CTX = 25   
    valid_contexts = valid_contexts[:MAX_CTX]

    final_raw_context = "\n\n---\n\n".join(valid_contexts)

    final_ans = await refine_answer(question, final_raw_context)

    return valid_contexts, final_ans
