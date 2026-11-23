import os
import re
import json
import sys
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc
from .config import settings
from .llm import openai_complete_if_cache
from .embedding import bge_m3_embedding

def safe_to_dict(item):
    """Chuẩn hóa dữ liệu đầu vào thành Dict"""
    if isinstance(item, dict):
        return item
    if isinstance(item, str):
        return {"content": item, "id": str(hash(item))}
    if isinstance(item, (list, tuple)) and len(item) > 0:
        content = str(item[0])
        score = item[1] if len(item) > 1 else 0.0
        return {"content": content, "score": score, "id": str(hash(content))}
    return {"content": str(item), "id": str(hash(str(item)))}

def extract_json_list(text):
    """
    Dùng Regex để tìm mảng JSON [ ... ] bất kể LLM nói nhảm gì xung quanh.
    """
    try:
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return None
    except Exception:
        return None


async def llm_rerank_func(query: str, **kwargs) -> list:
    documents = kwargs.get('documents') or kwargs.get('nodes') or []
    if not documents:
        return []
    
    # 1. Chuẩn hóa đầu vào
    normalized_docs = [safe_to_dict(doc) for doc in documents]
    
    docs_to_process = normalized_docs
    
    doc_list_str = ""
    for idx, doc in enumerate(docs_to_process):
        content = doc.get('content', '')
        # Chỉ lấy 500 ký tự đầu để LLM đọc nhanh
        preview = content[:500].replace("\n", " ") 
        doc_list_str += f"ID_{idx}: {preview}\n"

    # Prompt được tối ưu để trả về JSON thuần nhất có thể
    prompt = f"""
    You are a Financial Evidence Reranker for Vietnamese financial statement OCR retrieval.

    GOAL:
    Select the document IDs that are most useful for answering the query with verifiable financial evidence.

    QUERY:
    "{query}"

    DOCUMENT CANDIDATES:
    {doc_list_str}

    RERANKING PRINCIPLES:
    1. Prefer chunks that explicitly match the same company / ticker / report period in the query.
    2. Prefer chunks containing:
    - financial statement labels,
    - table rows,
    - note titles,
    - monetary values,
    - units,
    - line-item names,
    - “Mã số” anchors,
    - banking-specific labels for banks,
    - note/detail disclosures for analytical questions.
    3. For analytical questions, prefer chunks that contain underlying drivers or components, not only the surface wording.
    4. Prefer chunks with higher evidence density:
    - exact line items,
    - rows with numbers,
    - note disclosures,
    - sections that clearly identify the statement type.
    5. Avoid chunks that are generic, repetitive, purely narrative, or too vague to support an answer.
    6. If several chunks are complementary, keep all of them.
    7. Sort selected IDs from most useful to least useful.
    8. Select at most 12 IDs.

    OUTPUT RULE:
    Return JSON only.
    Valid examples:
    [3, 1, 7]
    []
    Do not explain anything.
    Do not return markdown.
    """
    try:
        response = await openai_complete_if_cache(
            prompt, 
            model_name=settings.REASONER_MODEL, 
            temperature=0.0,
            max_tokens=100
        )
        
        selected_ids = extract_json_list(response)
        
        if not selected_ids:
            # Nếu Regex không bắt được, thử fallback đơn giản
            if "[]" in response:
                return []
            # Nếu lỗi, in ra để debug
            print(f"⚠️ Rerank Parsing Failed. Raw response: {response[:100]}...", file=sys.stderr)
            return normalized_docs[:settings.RERANK_TOP_K]

        # 3. Map lại ID sang Document
        final_results = []
        for idx in selected_ids:
            if isinstance(idx, int) and 0 <= idx < len(docs_to_process):
                final_results.append(docs_to_process[idx])
        
        if not final_results:
            print("⚠️ LLM Rerank returned empty list. Using fallback.", file=sys.stderr)
            return normalized_docs[:settings.RERANK_TOP_K]
            
        print(f"✅ LLM Rerank: Selected {len(final_results)} chunks.", file=sys.stderr)
        return final_results

    except Exception as e:
        print(f"❌ Rerank Exception: {e}. Fallback used.", file=sys.stderr)
        return normalized_docs[:settings.RERANK_TOP_K]


def get_rag_engine(ticker: str, year: str, quarter: str):
    # Cấu trúc scaleable: rag_storage/CTG/2025/Q3
    work_dir = os.path.join(settings.BASE_WORKDIR, ticker.upper(), year, quarter.upper())
    
    if not os.path.exists(work_dir):
        os.makedirs(work_dir, exist_ok=True)

    return LightRAG(
        working_dir=work_dir,
        llm_model_func=openai_complete_if_cache,
        llm_model_name=settings.LLM_MODEL,
        llm_model_max_async=20,
        default_embedding_timeout=600,
        embedding_func=EmbeddingFunc(
            embedding_dim=1024,
            max_token_size=8192,
            func=bge_m3_embedding
        ),
        # rerank_model_func=llm_rerank_func,
        chunk_token_size=settings.CHUNK_SIZE,
        chunk_overlap_token_size=settings.CHUNK_OVERLAP,
        entity_extract_max_gleaning=1,
    )