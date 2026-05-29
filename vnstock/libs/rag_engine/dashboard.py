import os

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Financial RAG Debugger", layout="wide")

st.title("📊 Financial RAG Evaluation Debugger")
st.markdown("Dashboard này giúp soi lỗi và tối ưu các chỉ số Ragas cho Báo cáo tài chính.")

# --- LOAD DATA ---
@st.cache_data
def load_data(file_path):
    df = pd.read_csv(file_path)
    return df

# Đường dẫn mặc định đến file kết quả của bạn
report_file = "ragas_report.csv" 

if not os.path.exists(report_file):
    st.error(f"Không tìm thấy file {report_file}. Hãy chạy Eval trước!")
else:
    df = load_data(report_file)

    # --- SIDEBAR: THỐNG KÊ TỔNG QUAN ---
    st.sidebar.header("📈 Chỉ số trung bình")
    metrics = ["faithfulness", "answer_correctness", "answer_relevancy", "context_recall", "context_precision"]
    
    for m in metrics:
        if m in df.columns:
            avg_score = df[m].mean()
            color = "green" if avg_score >= 0.85 else "orange" if avg_score >= 0.7 else "red"
            st.sidebar.markdown(f"**{m.replace('_', ' ').title()}**: :{color}[{avg_score:.4f}]")

    # --- BỘ LỌC (FILTERS) ---
    st.sidebar.header("🔍 Bộ lọc")
    score_threshold = st.sidebar.slider("Chỉ hiện câu có Correctness dưới:", 0.0, 1.0, 1.0)
    search_query = st.sidebar.text_input("Tìm kiếm câu hỏi/ngân hàng:")

    # Apply filters
    filtered_df = df[df['answer_correctness'] <= score_threshold]
    if search_query:
        filtered_df = filtered_df[filtered_df['user_input'].str.contains(search_query, case=False)]

    # --- MAIN CONTENT ---
    
    # 1. Bảng tổng hợp nhanh
    st.subheader("Danh sách kết quả")
    
    # Định dạng màu sắc cho bảng
    def color_coding(val):
        color = '#ff4b4b' if val < 0.7 else '#ffa500' if val < 0.9 else '#2eb82e'
        return f'background-color: {color}; color: white'

    st.dataframe(filtered_df.style.applymap(color_coding, subset=metrics), use_container_width=True)

    # 2. Chi tiết từng câu hỏi (Debug Mode)
    st.divider()
    st.subheader("🕵️ Debug chi tiết từng câu")
    
    selected_idx = st.selectbox("Chọn câu hỏi để soi lỗi:", filtered_df.index)
    row = filtered_df.loc[selected_idx]

    col1, col2 = st.columns(2)
    
    with col1:
        st.info(f"**Câu hỏi:** {row['user_input']}")
        st.success(f"**AI Response:**\n{row['response']}")
        st.warning(f"**Ground Truth (Reference):**\n{row['reference']}")
        
    with col2:
        st.write("**Điểm số:**")
        cols = st.columns(len(metrics))
        for i, m in enumerate(metrics):
            cols[i].metric(m.split('_')[-1].title(), f"{row[m]:.2f}")
            
        st.write("**Context trích xuất được (Retrieved Context):**")
        try:
            # Ragas thường lưu context dạng string của list
            contexts = eval(row['retrieved_contexts'])
            for i, c in enumerate(contexts):
                st.caption(f"Chunk {i+1}:")
                st.code(c, language="text")
        except Exception:
            st.text(row['retrieved_contexts'])

    # 3. So sánh chuẩn hóa (Nếu có)
    if 'normalized_response' in df.columns:
        with st.expander("Xem so sánh sau khi chuẩn hóa (Normalize Compare)"):
            st.write(f"**Normalized Response:** {row['normalized_response']}")
            st.write(f"**Normalized Reference:** {row['normalized_reference']}")

