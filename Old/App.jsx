import { useState } from "react";

const API = "http://localhost:8002";

// ── Utility helpers ────────────────────────────────────────────────────────
const fmt = (v) => (v != null ? Number(v).toFixed(2) : "—");
const pct = (v) => (v != null ? `${Number(v).toFixed(2)}%` : "—");

function Badge({ value }) {
  const map = {
    LONG:         "badge-long",
    SHORT:        "badge-short",
    NEUTRAL:      "badge-neutral",
    TRADE:        "badge-trade",
    NO_TRADE:     "badge-notrade",
    LOW:          "badge-low",
    MEDIUM:       "badge-medium",
    HIGH:         "badge-high",
    DO_NOT_TRADE: "badge-notrade",
    TRENDING_UP:    "badge-long",
    TRENDING_DOWN:  "badge-short",
    CHOPPY:         "badge-neutral",
    HIGH_VOLATILITY:"badge-high",
  };
  return <span className={`badge ${map[value] || "badge-neutral"}`}>{value}</span>;
}

function AgentCard({ title, data, color }) {
  if (!data) return null;
  return (
    <div className="agent-card" style={{ "--accent": color }}>
      <div className="agent-header">
        <span className="agent-dot" />
        <span className="agent-title">{title}</span>
        {data.direction && <Badge value={data.direction} />}
        {data.risk_level && <Badge value={data.risk_level} />}
        {data.confidence != null && (
          <span className="confidence">{data.confidence}% conf</span>
        )}
      </div>
      <p className="agent-reasoning">{data.reasoning}</p>
      {data.market_regime && (
        <div className="agent-meta">
          Regime: <Badge value={data.market_regime} /> &nbsp;
          VIX: <Badge value={data.vix_assessment} />
        </div>
      )}
      {data.flags && data.flags.length > 0 && (
        <ul className="flag-list">
          {data.flags.map((f, i) => <li key={i}>⚠ {f}</li>)}
        </ul>
      )}
    </div>
  );
}

function TradePlan({ plan, ticker, price }) {
  if (!plan) return null;
  const isNoTrade = plan.verdict === "NO_TRADE";

  return (
    <div className={`trade-plan ${isNoTrade ? "no-trade" : ""}`}>
      <div className="plan-header">
        <div className="plan-ticker">{ticker}</div>
        <div className="plan-price">${fmt(price)}</div>
        <Badge value={plan.verdict} />
        {plan.direction && <Badge value={plan.direction} />}
        {plan.confidence != null && (
          <span className="confidence large">{plan.confidence}% confidence</span>
        )}
      </div>

      {isNoTrade ? (
        <div className="no-trade-reason">
          <span className="no-trade-icon">✕</span>
          <p>{plan.no_trade_reason || "Conditions do not favor a trade right now."}</p>
        </div>
      ) : (
        <div className="plan-grid">
          <div className="plan-block entry">
            <div className="block-label">Entry Zone</div>
            <div className="block-value">
              ${fmt(plan.entry_zone?.low)} – ${fmt(plan.entry_zone?.high)}
            </div>
          </div>
          <div className="plan-block stop">
            <div className="block-label">Stop Loss</div>
            <div className="block-value">${fmt(plan.stop_loss)}</div>
          </div>
          <div className="plan-block t1">
            <div className="block-label">Target 1 <span className="exit-pct">(exit 50%)</span></div>
            <div className="block-value">${fmt(plan.target_1?.price)}</div>
          </div>
          <div className="plan-block t2">
            <div className="block-label">Target 2 <span className="exit-pct">(exit 50%)</span></div>
            <div className="block-value">${fmt(plan.target_2?.price)}</div>
          </div>
          <div className="plan-block rr">
            <div className="block-label">Risk / Reward</div>
            <div className="block-value">{plan.risk_reward || "—"}</div>
          </div>
          <div className="plan-block time">
            <div className="block-label">Time Stop</div>
            <div className="block-value">{plan.time_stop || "4:00 PM ET"}</div>
          </div>
        </div>
      )}

      {plan.reasoning && (
        <div className="plan-reasoning">
          <span className="reasoning-label">Synthesis</span>
          <p>{plan.reasoning}</p>
        </div>
      )}

      {plan.wild_card_flags && plan.wild_card_flags.length > 0 && (
        <div className="wildcard-flags">
          {plan.wild_card_flags.map((f, i) => (
            <span key={i} className="wc-flag">⚠ {f}</span>
          ))}
        </div>
      )}

      {plan.position_notes && (
        <div className="position-notes">
          <span className="reasoning-label">Sizing</span>
          <p>{plan.position_notes}</p>
        </div>
      )}
    </div>
  );
}

function MarketBar({ ctx }) {
  if (!ctx) return null;
  return (
    <div className="market-bar">
      <span className="mkt-item">
        SPY <span className={ctx.spy_change >= 0 ? "up" : "dn"}>{pct(ctx.spy_change)}</span>
      </span>
      <span className="mkt-item">
        QQQ <span className={ctx.qqq_change >= 0 ? "up" : "dn"}>{pct(ctx.qqq_change)}</span>
      </span>
      <span className="mkt-item">
        VIX <span className="vix">{fmt(ctx.vix)}</span>
      </span>
    </div>
  );
}

export default function App() {
  const [ticker,  setTicker]  = useState("");
  const [loading, setLoading] = useState(false);
  const [result,  setResult]  = useState(null);
  const [error,   setError]   = useState(null);

  const analyze = async () => {
    if (!ticker.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/analyze`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ ticker: ticker.trim().toUpperCase() }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Request failed");
      }
      setResult(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const onKey = (e) => { if (e.key === "Enter") analyze(); };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap');

        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

        :root {
          --bg:       #0a0b0f;
          --surface:  #12141a;
          --border:   #1e2130;
          --text:     #e2e4ed;
          --muted:    #565d7a;
          --long:     #00e49a;
          --short:    #ff4d6d;
          --neutral:  #7b86b0;
          --gold:     #f5c842;
          --blue:     #4d9fff;
          --font-ui:  'Syne', sans-serif;
          --font-mono:'Space Mono', monospace;
        }

        body {
          background: var(--bg);
          color: var(--text);
          font-family: var(--font-ui);
          min-height: 100vh;
        }

        /* ── Header ── */
        .header {
          border-bottom: 1px solid var(--border);
          padding: 18px 32px;
          display: flex;
          align-items: center;
          gap: 16px;
        }
        .logo { font-size: 11px; font-family: var(--font-mono); color: var(--muted); letter-spacing: 0.12em; text-transform: uppercase; }
        .logo strong { color: var(--gold); }
        .mode-tag { font-size: 10px; font-family: var(--font-mono); background: #1a1e2a; border: 1px solid var(--border); padding: 3px 8px; border-radius: 3px; color: var(--blue); margin-left: auto; }

        /* ── Market bar ── */
        .market-bar {
          display: flex; gap: 24px; padding: 10px 32px;
          border-bottom: 1px solid var(--border);
          font-family: var(--font-mono); font-size: 12px;
          background: #0d0f14;
        }
        .mkt-item { color: var(--muted); }
        .mkt-item .up  { color: var(--long); }
        .mkt-item .dn  { color: var(--short); }
        .mkt-item .vix { color: var(--gold); }

        /* ── Main ── */
        .main { max-width: 900px; margin: 0 auto; padding: 40px 24px; }

        /* ── Search ── */
        .search-row {
          display: flex; gap: 12px; margin-bottom: 40px;
        }
        .ticker-input {
          flex: 1; background: var(--surface); border: 1px solid var(--border);
          color: var(--text); font-family: var(--font-mono); font-size: 22px;
          font-weight: 700; padding: 14px 20px; border-radius: 6px;
          text-transform: uppercase; letter-spacing: 0.08em;
          outline: none; transition: border-color 0.2s;
        }
        .ticker-input::placeholder { color: var(--muted); }
        .ticker-input:focus { border-color: var(--blue); }
        .analyze-btn {
          background: var(--blue); color: #fff; border: none;
          font-family: var(--font-ui); font-size: 14px; font-weight: 600;
          padding: 14px 32px; border-radius: 6px; cursor: pointer;
          letter-spacing: 0.05em; transition: opacity 0.2s;
        }
        .analyze-btn:disabled { opacity: 0.4; cursor: default; }
        .analyze-btn:hover:not(:disabled) { opacity: 0.85; }

        /* ── Loading ── */
        .loading-state {
          text-align: center; padding: 60px 0;
          font-family: var(--font-mono); color: var(--muted); font-size: 13px;
        }
        .spinner {
          width: 32px; height: 32px; border: 2px solid var(--border);
          border-top-color: var(--blue); border-radius: 50%;
          animation: spin 0.8s linear infinite; margin: 0 auto 16px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* ── Error ── */
        .error-box {
          background: rgba(255,77,109,0.08); border: 1px solid rgba(255,77,109,0.3);
          color: var(--short); padding: 16px 20px; border-radius: 6px; font-size: 14px;
          margin-bottom: 24px;
        }

        /* ── Trade Plan ── */
        .trade-plan {
          background: var(--surface); border: 1px solid var(--border);
          border-radius: 8px; padding: 24px; margin-bottom: 24px;
        }
        .trade-plan.no-trade { border-color: rgba(255,77,109,0.3); }

        .plan-header {
          display: flex; align-items: center; gap: 12px; margin-bottom: 20px;
          flex-wrap: wrap;
        }
        .plan-ticker { font-family: var(--font-mono); font-size: 26px; font-weight: 700; color: #fff; }
        .plan-price  { font-family: var(--font-mono); font-size: 18px; color: var(--muted); }

        .plan-grid {
          display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
          margin-bottom: 20px;
        }
        .plan-block {
          background: #0d0f14; border: 1px solid var(--border);
          border-radius: 6px; padding: 14px 16px;
        }
        .plan-block.entry { border-color: rgba(77,159,255,0.4); }
        .plan-block.stop  { border-color: rgba(255,77,109,0.3); }
        .plan-block.t1, .plan-block.t2 { border-color: rgba(0,228,154,0.3); }
        .block-label { font-size: 10px; font-family: var(--font-mono); color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
        .block-value { font-size: 18px; font-family: var(--font-mono); font-weight: 700; color: #fff; }
        .exit-pct    { font-size: 10px; color: var(--muted); }

        .no-trade-reason {
          display: flex; align-items: flex-start; gap: 16px;
          padding: 16px 0 20px;
        }
        .no-trade-icon { font-size: 28px; color: var(--short); }
        .no-trade-reason p { color: var(--muted); font-size: 14px; line-height: 1.6; }

        .plan-reasoning, .position-notes {
          border-top: 1px solid var(--border); padding-top: 16px; margin-top: 4px;
        }
        .reasoning-label {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.1em; display: block;
          margin-bottom: 8px;
        }
        .plan-reasoning p, .position-notes p {
          font-size: 13px; line-height: 1.7; color: #9da4c0;
        }

        .wildcard-flags {
          display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0 0;
        }
        .wc-flag {
          font-size: 11px; font-family: var(--font-mono);
          background: rgba(245,200,66,0.08); border: 1px solid rgba(245,200,66,0.2);
          color: var(--gold); padding: 4px 10px; border-radius: 4px;
        }

        /* ── Agent Cards ── */
        .agents-section { margin-top: 8px; }
        .agents-label {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.12em;
          margin-bottom: 12px; display: block;
        }
        .agents-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
        .agent-card {
          background: var(--surface); border: 1px solid var(--border);
          border-top: 2px solid var(--accent, var(--blue));
          border-radius: 6px; padding: 16px;
        }
        .agent-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
        .agent-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent, var(--blue)); }
        .agent-title { font-size: 11px; font-family: var(--font-mono); font-weight: 700; color: #fff; text-transform: uppercase; letter-spacing: 0.06em; }
        .agent-reasoning { font-size: 12px; line-height: 1.6; color: #7b86b0; }
        .agent-meta { font-size: 11px; color: var(--muted); margin-top: 8px; }
        .flag-list { margin-top: 8px; padding-left: 0; list-style: none; }
        .flag-list li { font-size: 11px; color: var(--gold); margin-bottom: 4px; }

        /* ── Badges ── */
        .badge {
          font-size: 10px; font-family: var(--font-mono); font-weight: 700;
          padding: 3px 8px; border-radius: 3px; text-transform: uppercase; letter-spacing: 0.06em;
        }
        .badge-long    { background: rgba(0,228,154,0.12); color: var(--long); border: 1px solid rgba(0,228,154,0.3); }
        .badge-short   { background: rgba(255,77,109,0.12); color: var(--short); border: 1px solid rgba(255,77,109,0.3); }
        .badge-neutral { background: rgba(123,134,176,0.1); color: var(--neutral); border: 1px solid rgba(123,134,176,0.2); }
        .badge-trade   { background: rgba(0,228,154,0.12); color: var(--long); border: 1px solid rgba(0,228,154,0.3); }
        .badge-notrade { background: rgba(255,77,109,0.12); color: var(--short); border: 1px solid rgba(255,77,109,0.3); }
        .badge-low     { background: rgba(0,228,154,0.1); color: var(--long); border: 1px solid rgba(0,228,154,0.2); }
        .badge-medium  { background: rgba(245,200,66,0.1); color: var(--gold); border: 1px solid rgba(245,200,66,0.2); }
        .badge-high    { background: rgba(255,77,109,0.1); color: var(--short); border: 1px solid rgba(255,77,109,0.2); }

        .confidence { font-size: 11px; font-family: var(--font-mono); color: var(--muted); }
        .confidence.large { font-size: 13px; color: var(--gold); }

        @media (max-width: 640px) {
          .plan-grid { grid-template-columns: repeat(2, 1fr); }
          .agents-grid { grid-template-columns: 1fr; }
        }
      `}</style>

      <div className="header">
        <div className="logo"><strong>HG</strong> · AI TRADING ENGINE</div>
        <div className="mode-tag">DAY TRADING</div>
      </div>

      {result && <MarketBar ctx={result.market_context} />}

      <div className="main">
        <div className="search-row">
          <input
            className="ticker-input"
            placeholder="AAPL"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            onKeyDown={onKey}
            maxLength={10}
          />
          <button className="analyze-btn" onClick={analyze} disabled={loading || !ticker.trim()}>
            {loading ? "Analyzing…" : "Analyze"}
          </button>
        </div>

        {loading && (
          <div className="loading-state">
            <div className="spinner" />
            Running MIKE · dispatching agents in parallel…
          </div>
        )}

        {error && <div className="error-box">⚠ {error}</div>}

        {result && (
          <>
            <TradePlan
              plan={result.trade_plan}
              ticker={result.ticker}
              price={result.price}
            />

            <div className="agents-section">
              <span className="agents-label">Agent Verdicts</span>
              <div className="agents-grid">
                <AgentCard
                  title="Technical"
                  data={result.agent_verdicts?.technical}
                  color="var(--blue)"
                />
                <AgentCard
                  title="Macro"
                  data={result.agent_verdicts?.macro}
                  color="var(--gold)"
                />
                <AgentCard
                  title="Wild Card"
                  data={result.agent_verdicts?.wildcard}
                  color="var(--short)"
                />
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}
