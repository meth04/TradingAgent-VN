# TradingAgent-VN

Hệ thống multi-agent phân tích và đầu tư chứng khoán Việt Nam: 

## Setup

```bash
# 1. Clone + venv
git clone <repo> sandbox && cd sandbox
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .\.venv\Scripts\Activate.ps1   # Windows PowerShell

# 2. Cài dependencies
pip install -r requirements.txt
pip install -r app/backend/requirements.txt
cd app/frontend && npm install && cd ../..
cd dashboard && npm install && cd ..

# 3. Cấu hình .env. :
#   CLIPROXY_BASE_URL=http://127.0.0.1:8317/v1
#   PRIMARY_MODEL=gpt-5.2   (cùng với T2_*, T3_*, T4_CIO, DAILY_REPORT)

# 4. PYTHONPATH cho session
export PYTHONPATH="$PWD:$PWD/vnstock:$PWD/tracking_news:$PWD/cognitive_trading"
# Windows: $env:PYTHONPATH = "$PWD;$PWD\vnstock;$PWD\tracking_news;$PWD\cognitive_trading"

# 5. Init DB
python -c "from vnstock.database.models import init_db; init_db()"
```

## Hướng dẫn chạy

### 1. Crawl dữ liệu

```bash
# Sync giá OHLCV vào data/vnstock.db
python run.py crawl_vnstock --tickers FPT,VCB,HPG    # hoặc VN30

# Crawl tin CafeF vào data/news.db
python run.py crawl_news --news-days 2 --source cafef

# Tất cả một lệnh (giá + tin + financial report)
python run.py sync --tickers FPT,VCB --year 2025 --quarter Q4 --news-days 3
```

### 2. Financial RAG

```bash
python run.py rag index --input vnstock/libs/data/financial_reports
python run.py rag query --query "Doanh thu và lợi nhuận Q1 2026 của FPT" --ticker FPT --year 2026 --quarter Q1 --mode hybrid
python run.py rag query --query "Rủi ro nợ xấu của VCB" --ticker VCB --year 2025 --quarter Q4 --mode hybrid      # global | local | hybrid
```

### 3. Sinh báo cáo phân tích tài chính (25 câu hỏi)

```bash
python run.py analyze --ticker FPT --year 2025 --quarter Q1
```
Output: `vnstock/analysis_reports/<TICKER>_<YEAR>_Q<n>.md`. Nếu file đã tồn tại → exit sớm (xoá để regenerate).

### 4. Backtest

```bash
# Legacy 3 workflow
python run.py backtest --tickers FPT,HPG,SSI,GAS,VCB --start 2026-03-24 --end 2026-03-25 --workflows Traditional,Kelly,Markowitz

# Cognitive pipeline
python -m cognitive_trading.runner --tickers VN30 --start 2026-01-05 --end 2026-01-26
```
Output: `backtest_results/`.

### 5. App real-time (`app/`)

```bash
# Backend (port 8000) — chạy từ root, không cần set PYTHONPATH
python app/start_backend.py

# Hoặc thủ công:
cd app/backend && python -m uvicorn main:app --port 8000 --reload

# Frontend (port 3001) — terminal khác
cd app/frontend && npm run dev
```
Mở `http://localhost:3001`. Trang chủ: chọn mã + workflow → bấm **Phân tích** → 5 agent cards stream → CIO → báo cáo Markdown. Còn 2 trang `/portfolio` và `/history`.

**Test backend qua curl**:
```bash
curl http://localhost:8000/api/health
curl -N -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"tickers":["FPT"],"workflow":"cognitive"}'
curl "http://localhost:8000/api/market/prices?tickers=FPT,VCB"
curl http://localhost:8000/api/portfolio/value
```

### 6. Dashboard backtest (`dashboard/`)

```bash
cd dashboard && npm run dev    # http://localhost:3000
```
Visualize artifacts từ `backtest_results/` (read-only, không cần backend).

### 7. MCP financial server (optional)

```bash
python -m vnstock.servers.financial_server
```

