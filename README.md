# Holy Grail Trading Engine

AI-powered day trading analysis using a multi-agent system (Claude) + Schwab market data.

## Architecture

```
User (React UI)
      │  POST /analyze { ticker }
      ▼
  FastAPI (main.py)
      │
      ▼
  MIKE Orchestrator (mike.py)
      │
      ├── DataCollector (Schwab API) ──► price bars + indicators + market context
      │
      ├── TechnicalAgent  ┐
      ├── MacroAgent      ├── run in PARALLEL via Claude
      ├── WildCardAgent   ┘
      │
      └── SupervisorAgent ──► Final trade plan
```

## Setup

### 1. Backend

```bash
cd backend
cp .env.example .env
# Fill in your API keys in .env

pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

### 2. Schwab OAuth Flow

Schwab uses OAuth2. Before you can call the API you need to complete the auth flow once to get an `access_token` and `refresh_token`.

**Quick way using schwab-py (optional helper library):**
```bash
pip install schwab-py
```

Or manually:
1. Go to https://developer.schwab.com/ and create an app
2. Set callback URL to `https://127.0.0.1:8182`
3. Follow OAuth flow to get tokens
4. Paste `access_token` and `refresh_token` into your `.env`

**Note:** Access tokens expire every 30 minutes. Refresh tokens last 7 days. You'll want to add a token-refresh mechanism for production use.

### 3. Frontend

```bash
cd frontend
npm install
npm start
# Opens at http://localhost:3000
```

## API

```
GET  /health          → { status, version }
POST /analyze         → { ticker: "AAPL" }
                      ← Full trade plan with agent verdicts
```

## Day Trading Config (config.py)

| Setting       | Value            |
|---------------|------------------|
| Timeframe     | 1-minute bars    |
| Lookback      | 5 days           |
| Bars to AI    | 240 (last 60 in prompt) |
| RSI Window    | 14               |
| EMAs          | 9, 20            |
| SMAs          | 20, 50, 100, 200 |
| MACD          | Yes              |
| Time Stop     | 4:00 PM ET       |

## Next Steps

- [ ] Add token refresh logic for Schwab OAuth
- [ ] SQLite trade log (store every plan + outcome)
- [ ] Win/loss tracker
- [ ] Expand to Scalp and Swing styles
# C-Users-randy-tos-trading-engine
