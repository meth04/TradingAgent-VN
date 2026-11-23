import asyncio
from pathlib import Path
from .core import get_rag_engine

def parse_filename(filename):
    # CTG-Q3-2025.ocr_text.txt -> Ticker, Year, Quarter
    parts = filename.split('-')
    if len(parts) >= 3:
        ticker = parts[0].upper()
        quarter = parts[1].upper()
        year = parts[2].split('.')[0]
        return ticker, year, quarter
    return "DEFAULT", "2025", "Q3"

async def _ingest_async(input_path: str, pattern: str):
    path_obj = Path(input_path)
    files = list(path_obj.rglob(pattern)) if path_obj.is_dir() else [path_obj]
    
    for file_path in files:
        ticker, year, quarter = parse_filename(file_path.name)
        print(f"\n>>> NẠP DỮ LIỆU: {ticker} | {quarter}-{year}")
        
        rag = get_rag_engine(ticker, year, quarter)
        await rag.initialize_storages()
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        reinforced = []
        tag = f"[{ticker} {quarter}/{year}]"
        for i, line in enumerate(lines):
            reinforced.append(f"{tag} {line}" if i % 5 == 0 else line)
            
        enhanced_content = f"TÀI LIỆU: {file_path.name}\n" + "\n".join(reinforced)
        await rag.ainsert(enhanced_content)
        print(f"✅ Đã lưu vào kho: {ticker}/{year}/{quarter}")

def run_ingest(input_path: str, pattern: str):
    asyncio.run(_ingest_async(input_path, pattern))