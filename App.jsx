import { useState, useEffect, Component } from "react";

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

function Bullets({ reasoning }) {
  if (!reasoning) return null;
  const lines = Array.isArray(reasoning) ? reasoning : [reasoning];
  return (
    <ul className="bullet-list">
      {lines.map((line, i) => <li key={i}>{line}</li>)}
    </ul>
  );
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
      <Bullets reasoning={data.reasoning} />
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

function TradePlan({ plan, ticker, price, onTakeTrade, tradeType }) {
  const [taking,    setTaking]    = useState(false);
  const [takeLabel, setTakeLabel] = useState("TAKE TRADE");

  if (!plan) return null;
  const isNoTrade = plan.verdict === "NO_TRADE";

  const handleTake = async () => {
    if (taking) return;
    setTaking(true);
    try {
      await onTakeTrade({
        symbol:     ticker,
        direction:  plan.direction === "LONG" ? "LONG" : "SHORT",
        stop:       plan.stop_loss,
        target:     plan.target_1?.price,
        target_2:   plan.target_2?.price,
        trade_type: tradeType || "scalp",
      });
      setTakeLabel("Trade Added ✓");
      setTimeout(() => { setTakeLabel("TAKE TRADE"); setTaking(false); }, 2000);
    } catch {
      setTaking(false);
    }
  };

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
        {!isNoTrade && onTakeTrade && (
          <button
            className={`take-trade-btn ${takeLabel !== "TAKE TRADE" ? "taken" : ""}`}
            onClick={handleTake}
            disabled={taking && takeLabel === "TAKE TRADE"}
          >
            {takeLabel}
          </button>
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
          <Bullets reasoning={plan.reasoning} />
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

// ── Trade Tracker ────────────────────────────────────────────────────────────

const STATUS_COLOR = {
  OPEN:          "var(--blue)",
  CONFIRMED:     "var(--gold)",
  STOPPED:       "var(--short)",
  TARGET_HIT:    "var(--long)",
  TARGET_1_HIT:  "var(--gold)",
  EXPIRED:       "var(--muted)",
  CLOSED:        "var(--muted)",
};

function TradeRow({ trade, onClose, onCopy }) {
  const dir   = trade.direction?.toUpperCase();
  const emoji = dir === "LONG" ? "🟢" : "🔴";
  const pnl   = trade.out_t1_pnl ?? trade.out_30m_pnl ?? trade.out_15m_pnl
              ?? trade.out_10m_pnl ?? trade.out_5m_pnl
              ?? trade.out_1d_pnl  ?? trade.out_3d_pnl  ?? trade.out_7d_pnl;
  const pnlStr = pnl != null
    ? <span style={{ color: pnl >= 0 ? "var(--long)" : "var(--short)" }}>{pnl >= 0 ? "+" : ""}{pnl.toFixed(2)}%</span>
    : <span style={{ color: "var(--muted)" }}>—</span>;
  const isOpen = ["OPEN","CONFIRMED","TARGET_1_HIT"].includes(trade.status);
  const t1Hit  = trade.status === "TARGET_1_HIT";
  return (
    <tr>
      <td className="mono">{emoji} {trade.symbol}</td>
      <td><Badge value={dir} /></td>
      <td className="mono">${fmt(trade.entry_price)}</td>
      <td className="mono">${fmt(trade.stop)}</td>
      <td className="mono" style={{ color: t1Hit ? "var(--long)" : undefined }}>
        {t1Hit ? "✓" : `$${fmt(trade.target)}`}
      </td>
      <td className="mono" style={{ color: trade.target_2 ? undefined : "var(--muted)" }}>
        {trade.target_2 ? `$${fmt(trade.target_2)}` : "—"}
      </td>
      <td><span style={{ color: STATUS_COLOR[trade.status] || "var(--muted)", fontSize: 11 }}>{trade.status}</span></td>
      <td className="mono">{pnlStr}</td>
      <td className="mono">{trade.trade_type}</td>
      <td>
        <div style={{ display: "flex", gap: 6 }}>
          <button className="tbl-btn copy-btn" title="Copy to Discord" onClick={() => onCopy(trade)}>[C]</button>
          {isOpen && (
            <button className="tbl-btn close-btn" onClick={() => onClose(trade.trade_id)}>Close</button>
          )}
        </div>
      </td>
    </tr>
  );
}

// ── Error boundary — catches render crashes inside TradeTracker ──────────────
class TrackerErrorBoundary extends Component {
  state = { error: null };
  static getDerivedStateFromError(e) { return { error: e.message }; }
  render() {
    if (this.state.error) return (
      <div style={{
        marginTop: 40, padding: "16px 20px", borderRadius: 6,
        background: "rgba(255,77,109,0.08)", border: "1px solid rgba(255,77,109,0.3)",
        color: "#ff4d6d", fontFamily: "monospace", fontSize: 13,
      }}>
        TradeTracker crashed: {this.state.error}
        <button style={{ marginLeft: 16, cursor: "pointer", background: "none", border: "1px solid #ff4d6d", color: "#ff4d6d", borderRadius: 4, padding: "2px 8px" }}
          onClick={() => this.setState({ error: null })}>retry</button>
      </div>
    );
    return this.props.children;
  }
}

function TradeTracker({ result, tradeType, refreshKey }) {
  const [trades,     setTrades]     = useState([]);
  const [loadError,  setLoadError]  = useState(null);
  const [showForm,   setShowForm]   = useState(false);
  const [copied,     setCopied]     = useState(null);
  const [form,       setForm]       = useState({
    symbol: "", direction: "LONG", entry_price: "", stop: "", target: "", target_2: "",
    trade_type: tradeType || "scalp", notes: "",
  });

  const loadTrades = async () => {
    try {
      const res = await fetch(`${API}/trades?limit=50`);
      if (res.ok) {
        const data = await res.json();
        setTrades(Array.isArray(data) ? data : []);
        setLoadError(null);
      } else {
        const msg = `API ${res.status}: ${res.statusText}`;
        setLoadError(msg);
        console.error("[TradeTracker] /trades error:", msg);
      }
    } catch (e) {
      const msg = `Cannot reach API — ${e.message}`;
      setLoadError(msg);
      console.error("[TradeTracker] fetch failed:", e);
    }
  };

  useEffect(() => {
    loadTrades();
    const id = setInterval(loadTrades, 15000);
    return () => clearInterval(id);
  }, []);

  // Reload when parent signals a new trade was added (e.g. via TAKE TRADE)
  useEffect(() => { if (refreshKey) loadTrades(); }, [refreshKey]);

  // Pre-fill form from latest analysis
  useEffect(() => {
    if (result?.ticker)                        setForm(f => ({ ...f, symbol:      result.ticker }));
    if (result?.trade_plan?.entry_zone?.low)   setForm(f => ({ ...f, entry_price: String(result.trade_plan.entry_zone.low) }));
    if (result?.trade_plan?.stop_loss)         setForm(f => ({ ...f, stop:        String(result.trade_plan.stop_loss) }));
    if (result?.trade_plan?.target_1?.price)   setForm(f => ({ ...f, target:      String(result.trade_plan.target_1.price) }));
    if (result?.trade_plan?.target_2?.price)   setForm(f => ({ ...f, target_2:    String(result.trade_plan.target_2.price) }));
  }, [result]);

  // Sync trade_type with parent
  useEffect(() => { setForm(f => ({ ...f, trade_type: tradeType || "scalp" })); }, [tradeType]);

  const handleAdd = async () => {
    if (!form.symbol || !form.entry_price || !form.stop || !form.target) return;
    try {
      const res = await fetch(`${API}/trades`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...form,
          entry_price: parseFloat(form.entry_price),
          stop:        parseFloat(form.stop),
          target:      parseFloat(form.target),
          target_2:    form.target_2 ? parseFloat(form.target_2) : null,
        }),
      });
      if (res.ok) { setShowForm(false); loadTrades(); }
    } catch {}
  };

  const handleClose = async (tid) => {
    const price = prompt("Exit price:");
    if (!price) return;
    await fetch(`${API}/trades/${tid}/close`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exit_price: parseFloat(price), exit_reason: "MANUAL" }),
    });
    loadTrades();
  };

  const handleCopy = async (trade) => {
    try {
      const res  = await fetch(`${API}/trades/${trade.trade_id}/discord`);
      const data = await res.json();
      await navigator.clipboard.writeText(data.formatted);
      setCopied(trade.trade_id);
      setTimeout(() => setCopied(null), 2000);
    } catch {}
  };

  const safeTrades = Array.isArray(trades) ? trades : [];
  const open   = safeTrades.filter(t => ["OPEN","CONFIRMED"].includes(t.status));
  const closed = safeTrades.filter(t => !["OPEN","CONFIRMED"].includes(t.status));

  return (
    <div className="tracker-section">
      <div className="tracker-header">
        <span className="section-label">Trade Tracker</span>
        <button className="tbl-btn add-btn" onClick={() => setShowForm(s => !s)}>
          {showForm ? "Cancel" : "+ Add Trade"}
        </button>
      </div>

      {loadError && (
        <div style={{ fontSize: 12, fontFamily: "monospace", color: "var(--short)",
          background: "rgba(255,77,109,0.06)", border: "1px solid rgba(255,77,109,0.2)",
          borderRadius: 6, padding: "8px 12px", marginBottom: 12 }}>
          ⚠ {loadError}
        </div>
      )}

      {copied && <div className="copy-toast">Copied to clipboard ✓</div>}

      {showForm && (
        <div className="add-form">
          <div className="form-row">
            <input className="form-input" placeholder="Symbol" value={form.symbol}
              onChange={e => setForm(f => ({ ...f, symbol: e.target.value.toUpperCase() }))} />
            <select className="form-input" value={form.direction}
              onChange={e => setForm(f => ({ ...f, direction: e.target.value }))}>
              <option value="LONG">LONG</option>
              <option value="SHORT">SHORT</option>
            </select>
            <select className="form-input" value={form.trade_type}
              onChange={e => setForm(f => ({ ...f, trade_type: e.target.value }))}>
              <option value="scalp">Scalp</option>
              <option value="swing">Swing</option>
            </select>
          </div>
          <div className="form-row">
            <input className="form-input" placeholder="Entry" type="number" value={form.entry_price}
              onChange={e => setForm(f => ({ ...f, entry_price: e.target.value }))} />
            <input className="form-input" placeholder="Stop" type="number" value={form.stop}
              onChange={e => setForm(f => ({ ...f, stop: e.target.value }))} />
            <input className="form-input" placeholder="Target 1" type="number" value={form.target}
              onChange={e => setForm(f => ({ ...f, target: e.target.value }))} />
            <input className="form-input" placeholder="Target 2 (opt)" type="number" value={form.target_2}
              onChange={e => setForm(f => ({ ...f, target_2: e.target.value }))} />
          </div>
          <div className="form-row">
            <input className="form-input" placeholder="Notes (optional)" value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} style={{ flex: 3 }} />
            <button className="tbl-btn add-btn" onClick={handleAdd}>Save Trade</button>
          </div>
        </div>
      )}

      {open.length > 0 && (
        <>
          <div className="tbl-label">Open ({open.length})</div>
          <table className="trade-table">
            <thead><tr>
              <th>Symbol</th><th>Dir</th><th>Entry</th><th>Stop</th>
              <th>T1</th><th>T2</th><th>Status</th><th>P&amp;L</th><th>Type</th><th></th>
            </tr></thead>
            <tbody>
              {open.map(t => (
                <TradeRow key={t.trade_id} trade={t} onClose={handleClose} onCopy={handleCopy} />
              ))}
            </tbody>
          </table>
        </>
      )}

      {closed.length > 0 && (
        <>
          <div className="tbl-label" style={{ marginTop: 20 }}>Recent Closed ({closed.length})</div>
          <table className="trade-table">
            <thead><tr>
              <th>Symbol</th><th>Dir</th><th>Entry</th><th>Stop</th>
              <th>T1</th><th>T2</th><th>Status</th><th>P&amp;L</th><th>Type</th><th></th>
            </tr></thead>
            <tbody>
              {closed.slice(0, 10).map(t => (
                <TradeRow key={t.trade_id} trade={t} onClose={handleClose} onCopy={handleCopy} />
              ))}
            </tbody>
          </table>
        </>
      )}

      {safeTrades.length === 0 && !loadError && (
        <div className="empty-trades">No trades yet — click + Add Trade to log one.</div>
      )}
    </div>
  );
}


// ── History / Analysis Log ─────────────────────────────────────────────────

function HistorySection() {
  const [logs,    setLogs]    = useState([]);
  const [filter,  setFilter]  = useState("ALL");
  const [loading, setLoading] = useState(false);

  const loadLogs = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/logs?limit=100`);
      if (res.ok) setLogs(await res.json());
    } catch {}
    setLoading(false);
  };

  useEffect(() => { loadLogs(); }, []);

  const filtered = logs.filter(l => {
    if (filter === "TRADE")    return l.verdict === "TRADE";
    if (filter === "NO_TRADE") return l.verdict === "NO_TRADE";
    if (filter === "Correct")  return l.out_30m_correct === true;
    if (filter === "Wrong")    return l.out_30m_correct === false;
    return true;
  });

  const tradeLogs = logs.filter(l => l.verdict === "TRADE");
  const resolved  = tradeLogs.filter(l => l.out_30m_correct != null);
  const correct   = resolved.filter(l => l.out_30m_correct === true);
  const hitRate   = resolved.length > 0
    ? Math.round((correct.length / resolved.length) * 100)
    : null;

  const pnlColor = (v) => {
    if (v == null) return "var(--muted)";
    return v >= 0 ? "var(--long)" : "var(--short)";
  };
  const pnlStr = (v) => {
    if (v == null) return <span style={{ color: "var(--muted)" }}>—</span>;
    return <span style={{ color: pnlColor(v) }}>{v >= 0 ? "+" : ""}{Number(v).toFixed(2)}%</span>;
  };

  return (
    <div className="history-section">
      <div className="tracker-header">
        <span className="section-label">Analysis History</span>
        <button className="tbl-btn add-btn" onClick={loadLogs} disabled={loading}>
          {loading ? "…" : "↻ Refresh"}
        </button>
      </div>

      {hitRate != null && (
        <div className="hit-rate-bar">
          <span className="hit-rate-label">30m Hit Rate (TRADE verdicts)</span>
          <span className="hit-rate-value" style={{ color: hitRate >= 50 ? "var(--long)" : "var(--short)" }}>
            {hitRate}%
          </span>
          <span className="hit-rate-sub">({correct.length}/{resolved.length} resolved)</span>
        </div>
      )}

      <div className="filter-row">
        {["ALL","TRADE","NO_TRADE","Correct","Wrong"].map(f => (
          <button key={f}
            className={`filter-btn ${filter === f ? "active" : ""}`}
            onClick={() => setFilter(f)}>{f}</button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-trades">No logs match this filter.</div>
      ) : (
        <table className="trade-table" style={{ fontSize: 11 }}>
          <thead><tr>
            <th>Time</th><th>Symbol</th><th>Verdict</th><th>Dir</th><th>Conf</th>
            <th>Stop</th><th>T1</th><th>T2</th>
            <th>5m P&L</th><th>15m P&L</th><th>30m P&L</th><th>Correct?</th>
          </tr></thead>
          <tbody>
            {filtered.map(l => {
              const dt = l.created_at ? new Date(l.created_at).toLocaleString("en-US", {
                month: "numeric", day: "numeric",
                hour: "2-digit", minute: "2-digit",
              }) : "—";
              const correct30 = l.out_30m_correct;
              return (
                <tr key={l.id}>
                  <td className="mono" style={{ color: "var(--muted)", fontSize: 10 }}>{dt}</td>
                  <td className="mono" style={{ fontWeight: 700 }}>{l.ticker}</td>
                  <td><Badge value={l.verdict} /></td>
                  <td>{l.direction ? <Badge value={l.direction} /> : "—"}</td>
                  <td className="mono" style={{ color: "var(--muted)" }}>{l.confidence != null ? `${l.confidence}%` : "—"}</td>
                  <td className="mono">{l.stop_loss  ? `$${fmt(l.stop_loss)}` : "—"}</td>
                  <td className="mono">{l.target_1   ? `$${fmt(l.target_1)}`  : "—"}</td>
                  <td className="mono">{l.target_2   ? `$${fmt(l.target_2)}`  : "—"}</td>
                  <td className="mono">{pnlStr(l.out_5m_pnl)}</td>
                  <td className="mono">{pnlStr(l.out_15m_pnl)}</td>
                  <td className="mono">{pnlStr(l.out_30m_pnl)}</td>
                  <td style={{ fontSize: 13 }}>
                    {correct30 == null
                      ? <span style={{ color: "var(--muted)" }}>…</span>
                      : correct30
                        ? <span style={{ color: "var(--long)" }}>✓</span>
                        : <span style={{ color: "var(--short)" }}>✗</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}


// ── Main App ─────────────────────────────────────────────────────────────────

export default function App() {
  const [ticker,     setTicker]     = useState("");
  const [loading,    setLoading]    = useState(false);
  const [result,     setResult]     = useState(null);
  const [error,      setError]      = useState(null);
  const [tradeType,  setTradeType]  = useState("scalp");
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeTab,  setActiveTab]  = useState("TRADES");
  const trackerRef = { current: null };

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

  const handleTakeTrade = async (params) => {
    const qRes = await fetch(`${API}/quote/${params.symbol}`);
    if (!qRes.ok) throw new Error("Quote unavailable");
    const { price } = await qRes.json();
    await fetch(`${API}/trades`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...params, entry_price: price }),
    });
    setRefreshKey(k => k + 1);
    setActiveTab("TRADES");
    setTimeout(() => {
      document.getElementById("bottom-tabs")?.scrollIntoView({ behavior: "smooth" });
    }, 100);
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

        /* ── Bullet list (agent reasoning) ── */
        .bullet-list {
          list-style: none; padding: 0; margin: 0;
        }
        .bullet-list li {
          font-size: 12px; line-height: 1.7; color: #7b86b0;
          padding-left: 4px;
        }
        .plan-reasoning .bullet-list li { font-size: 13px; color: #9da4c0; }

        /* ── Trade Tracker ── */
        .tracker-section {
          margin-top: 40px; border-top: 1px solid var(--border); padding-top: 32px;
        }
        .tracker-header {
          display: flex; align-items: center; justify-content: space-between;
          margin-bottom: 16px;
        }
        .section-label {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.12em;
        }
        .tbl-label {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px;
        }
        .add-form {
          background: var(--surface); border: 1px solid var(--border);
          border-radius: 8px; padding: 16px; margin-bottom: 20px;
          display: flex; flex-direction: column; gap: 10px;
        }
        .form-row { display: flex; gap: 8px; }
        .form-input {
          background: var(--bg); border: 1px solid var(--border);
          color: var(--text); border-radius: 6px; padding: 8px 10px;
          font-family: var(--font-mono); font-size: 12px; flex: 1;
        }
        .form-input:focus { outline: none; border-color: var(--blue); }

        .trade-table {
          width: 100%; border-collapse: collapse; font-size: 12px;
          font-family: var(--font-mono);
        }
        .trade-table th {
          text-align: left; color: var(--muted); font-size: 10px;
          text-transform: uppercase; letter-spacing: 0.08em;
          padding: 6px 10px; border-bottom: 1px solid var(--border);
        }
        .trade-table td {
          padding: 9px 10px; border-bottom: 1px solid rgba(30,33,48,0.6);
          vertical-align: middle;
        }
        .trade-table tr:hover td { background: rgba(255,255,255,0.02); }
        .mono { font-family: var(--font-mono); }

        .tbl-btn {
          font-size: 11px; font-family: var(--font-mono); font-weight: 700;
          padding: 4px 10px; border-radius: 4px; cursor: pointer; border: none;
          transition: opacity 0.15s;
        }
        .tbl-btn:hover { opacity: 0.8; }
        .copy-btn  { background: rgba(77,159,255,0.15); color: var(--blue); border: 1px solid rgba(77,159,255,0.3); }
        .close-btn { background: rgba(255,77,109,0.12); color: var(--short); border: 1px solid rgba(255,77,109,0.3); }
        .add-btn   { background: rgba(0,228,154,0.12);  color: var(--long);  border: 1px solid rgba(0,228,154,0.3); }

        .copy-toast {
          font-size: 12px; font-family: var(--font-mono); color: var(--long);
          background: rgba(0,228,154,0.08); border: 1px solid rgba(0,228,154,0.2);
          padding: 8px 14px; border-radius: 6px; margin-bottom: 12px;
          display: inline-block;
        }
        .empty-trades {
          color: var(--muted); font-size: 13px; padding: 24px 0; text-align: center;
        }

        /* ── Take Trade button ── */
        .take-trade-btn {
          margin-left: auto;
          background: rgba(0,228,154,0.15); color: var(--long);
          border: 1px solid rgba(0,228,154,0.4);
          font-family: var(--font-mono); font-size: 11px; font-weight: 700;
          padding: 6px 16px; border-radius: 4px; cursor: pointer;
          letter-spacing: 0.08em; transition: opacity 0.15s, background 0.2s;
        }
        .take-trade-btn:hover { opacity: 0.85; }
        .take-trade-btn.taken {
          background: rgba(0,228,154,0.25); cursor: default;
        }

        /* ── Tabs ── */
        .tab-bar {
          display: flex; gap: 4px; margin-bottom: 24px;
        }
        .tab-btn {
          font-size: 11px; font-family: var(--font-mono); font-weight: 700;
          padding: 6px 18px; border-radius: 4px; cursor: pointer;
          border: 1px solid var(--border); background: var(--surface);
          color: var(--muted); letter-spacing: 0.08em; transition: all 0.15s;
        }
        .tab-btn.active {
          background: rgba(77,159,255,0.12); color: var(--blue);
          border-color: rgba(77,159,255,0.3);
        }
        .tab-btn:hover:not(.active) { color: var(--text); }

        /* ── History section ── */
        .history-section { }
        .hit-rate-bar {
          display: flex; align-items: center; gap: 10px;
          background: var(--surface); border: 1px solid var(--border);
          border-radius: 6px; padding: 10px 16px; margin-bottom: 16px;
        }
        .hit-rate-label { font-size: 11px; font-family: var(--font-mono); color: var(--muted); }
        .hit-rate-value { font-size: 20px; font-family: var(--font-mono); font-weight: 700; }
        .hit-rate-sub   { font-size: 11px; font-family: var(--font-mono); color: var(--muted); }

        .filter-row { display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap; }
        .filter-btn {
          font-size: 10px; font-family: var(--font-mono); font-weight: 700;
          padding: 4px 10px; border-radius: 3px; cursor: pointer;
          border: 1px solid var(--border); background: var(--surface);
          color: var(--muted); transition: all 0.15s;
        }
        .filter-btn.active {
          background: rgba(77,159,255,0.12); color: var(--blue);
          border-color: rgba(77,159,255,0.3);
        }
        .filter-btn:hover:not(.active) { color: var(--text); }

        @media (max-width: 640px) {
          .plan-grid { grid-template-columns: repeat(2, 1fr); }
          .agents-grid { grid-template-columns: 1fr; }
          .trade-table { font-size: 11px; }
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
            Running checker agents in parallel…
          </div>
        )}

        {error && <div className="error-box">⚠ {error}</div>}

        {result && (
          <>
            <TradePlan
              plan={result.trade_plan}
              ticker={result.ticker}
              price={result.price}
              tradeType={tradeType}
              onTakeTrade={handleTakeTrade}
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

        <div id="bottom-tabs" style={{ marginTop: 40, borderTop: "1px solid var(--border)", paddingTop: 24 }}>
          <div className="tab-bar">
            {["TRADES","HISTORY"].map(t => (
              <button key={t} className={`tab-btn ${activeTab === t ? "active" : ""}`}
                onClick={() => setActiveTab(t)}>{t}</button>
            ))}
          </div>
          <TrackerErrorBoundary>
            {activeTab === "TRADES"
              ? <TradeTracker result={result} tradeType={tradeType} refreshKey={refreshKey} />
              : <HistorySection />}
          </TrackerErrorBoundary>
        </div>
      </div>
    </>
  );
}
