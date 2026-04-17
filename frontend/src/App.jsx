import { useState, useEffect, useRef, Component } from "react";

const API = "http://localhost:8002";

// ── Utility helpers ────────────────────────────────────────────────────────
const fmt = (v) => (v != null ? Number(v).toFixed(2) : "—");
const pct = (v) => (v != null ? `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}%` : "—");
const fmtTime = (s) => {
  if (!s) return "—";
  try { return new Date(s).toLocaleString(); } catch { return s; }
};

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

// Filter ACTION bullets from agent reasoning (they move to Synthesis)
function filterActionBullets(reasoning) {
  if (!reasoning) return [];
  const lines = Array.isArray(reasoning) ? reasoning : [reasoning];
  return lines.filter(l => !String(l).startsWith("• ACTION:"));
}

function extractActionBullet(reasoning) {
  if (!reasoning) return null;
  const lines = Array.isArray(reasoning) ? reasoning : [reasoning];
  return lines.find(l => String(l).startsWith("• ACTION:")) || null;
}

function AgentCard({ title, data, color }) {
  if (!data) return null;
  const filtered = filterActionBullets(data.reasoning);
  return (
    <div className="agent-card" style={{ "--accent": color }}>
      <div className="agent-header">
        <span className="agent-dot" />
        <span className="agent-title">{title}</span>
        {data.direction && <Badge value={data.direction} />}
        {data.risk_level && <Badge value={data.risk_level} />}
        {data.confidence != null && (
          <span className="confidence">{data.confidence}%</span>
        )}
      </div>
      <Bullets reasoning={filtered} />
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

function TradePlan({ plan, ticker, price, onAddTrade, onTakeTrade, tradeType, agentVerdicts }) {
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
        trade_type: tradeType === "swing" ? "swing" : "scalp",
      });
      setTakeLabel("Trade Added ✓");
      setTimeout(() => { setTakeLabel("TAKE TRADE"); setTaking(false); }, 2000);
    } catch {
      setTaking(false);
    }
  };

  // Collect ACTION bullets from agent verdicts to show in Synthesis
  const actionBullets = [];
  if (agentVerdicts) {
    for (const [name, verdict] of Object.entries(agentVerdicts)) {
      const ab = extractActionBullet(verdict?.reasoning);
      if (ab) actionBullets.push({ name: name.replace("Agent", "").toUpperCase(), text: ab });
    }
  }

  const ts = plan.tomorrow_setup;

  return (
    <div className={`trade-plan ${isNoTrade ? "no-trade" : ""}`}>
      <div className="plan-header">
        <div className="plan-ticker">{ticker}</div>
        <div className="plan-price">${fmt(price)}</div>
        <Badge value={plan.verdict} />
        {plan.direction && <Badge value={plan.direction} />}
        {plan.confidence != null && (
          <span className="confidence large">{plan.confidence}%</span>
        )}
        {!isNoTrade && (
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button className="tbl-btn add-btn" onClick={onAddTrade}>+ ADD TRADE</button>
            {onTakeTrade && (
              <button
                className={`take-trade-btn ${takeLabel !== "TAKE TRADE" ? "taken" : ""}`}
                onClick={handleTake}
                disabled={taking && takeLabel === "TAKE TRADE"}
              >
                {takeLabel}
              </button>
            )}
          </div>
        )}
      </div>

      {isNoTrade && !ts ? (
        <div className="no-trade-reason">
          <span className="no-trade-icon">✕</span>
          <p>{plan.no_trade_reason || "Conditions do not favor a trade right now."}</p>
        </div>
      ) : !isNoTrade ? (
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
      ) : null}

      {/* Tomorrow's Setup */}
      {ts && (
        <div className="tomorrow-setup">
          <div className="tomorrow-header">TOMORROW'S SETUP</div>
          <div className="tomorrow-grid">
            <div className="tomorrow-block">
              <div className="t-label">Bias</div>
              <div className="t-value"><Badge value={ts.bias} /></div>
            </div>
            <div className="tomorrow-block">
              <div className="t-label">Entry Zone</div>
              <div className="t-value">${fmt(ts.entry_zone?.low)} – ${fmt(ts.entry_zone?.high)}</div>
            </div>
            <div className="tomorrow-block">
              <div className="t-label">Stop</div>
              <div className="t-value">${fmt(ts.stop)}</div>
            </div>
            <div className="tomorrow-block">
              <div className="t-label">Target 1</div>
              <div className="t-value">${fmt(ts.target_1?.price)}</div>
            </div>
            <div className="tomorrow-block">
              <div className="t-label">Target 2</div>
              <div className="t-value">${fmt(ts.target_2?.price)}</div>
            </div>
            <div className="tomorrow-block">
              <div className="t-label">Confidence</div>
              <div className="t-value" style={{ color: "var(--gold)", fontWeight: 700 }}>{ts.confidence}%</div>
            </div>
          </div>
          {ts.void_conditions?.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div className="t-label" style={{ marginBottom: 6 }}>VOID IF</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {ts.void_conditions.map((vc, i) => (
                  <span key={i} className="void-badge">⚠ {vc}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Synthesis — ACTION bullets from agents + supervisor reasoning */}
      {(plan.reasoning || actionBullets.length > 0) && (
        <div className="plan-reasoning">
          <span className="reasoning-label">Synthesis</span>
          {actionBullets.length > 0 && (
            <ul className="bullet-list action-list" style={{ marginBottom: 6 }}>
              {actionBullets.map((ab, i) => (
                <li key={i} style={{ color: "var(--gold)" }}>
                  [{ab.name}] {ab.text}
                </li>
              ))}
            </ul>
          )}
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
    </div>
  );
}

function MarketBar({ ctx }) {
  if (!ctx) return null;
  return (
    <div className="market-bar">
      <span className="mkt-item">
        <span className="mkt-label">SPY</span>
        {ctx.spy_price != null && <span className="mkt-price"> ${fmt(ctx.spy_price)}</span>}
        {" "}<span className={ctx.spy_change >= 0 ? "up" : "dn"}>{pct(ctx.spy_change)}</span>
      </span>
      <span className="mkt-item">
        <span className="mkt-label">QQQ</span>
        {ctx.qqq_price != null && <span className="mkt-price"> ${fmt(ctx.qqq_price)}</span>}
        {" "}<span className={ctx.qqq_change >= 0 ? "up" : "dn"}>{pct(ctx.qqq_change)}</span>
      </span>
      <span className="mkt-item">
        <span className="mkt-label">VIX</span>
        {" "}<span className="vix">{fmt(ctx.vix)}</span>
      </span>
    </div>
  );
}

// ── Trade Checker ─────────────────────────────────────────────────────────────

function TradeChecker() {
  const [trades,       setTrades]       = useState([]);
  const [checking,     setChecking]     = useState({});
  const [lastChecked,  setLastChecked]  = useState({});
  const [livePrices,   setLivePrices]   = useState({});

  const loadOpenTrades = async () => {
    try {
      const res = await fetch(`${API}/trades?limit=100`);
      if (!res.ok) return;
      const data = await res.json();
      const open = (Array.isArray(data) ? data : []).filter(
        t => t.status === "OPEN" || t.status === "CONFIRMED"
      );
      setTrades(open);
    } catch {}
  };

  const checkTrade = async (trade) => {
    setChecking(c => ({ ...c, [trade.trade_id]: true }));
    try {
      const res = await fetch(`${API}/trades/${trade.trade_id}`);
      if (res.ok) {
        const updated = await res.json();
        const ts = new Date().toLocaleTimeString();
        setLastChecked(lc => ({ ...lc, [trade.trade_id]: ts }));
        await loadOpenTrades();
        if (updated.last_price != null) {
          setLivePrices(lp => ({ ...lp, [trade.trade_id]: updated.last_price }));
        }
      }
    } catch {}
    setChecking(c => ({ ...c, [trade.trade_id]: false }));
  };

  const checkAll = async () => {
    for (const t of trades) await checkTrade(t);
  };

  useEffect(() => {
    loadOpenTrades();
    const id = setInterval(checkAll, 30000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (trades.length === 0) return;
    const id = setInterval(checkAll, 30000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trades.length]);

  if (trades.length === 0) return null;

  const calcPnl = (trade) => {
    const price = livePrices[trade.trade_id] ?? null;
    if (price == null || !trade.entry_price) return null;
    const diff = price - trade.entry_price;
    const pnlPct = (diff / trade.entry_price) * 100;
    return trade.direction?.toUpperCase() === "SHORT" ? -pnlPct : pnlPct;
  };

  return (
    <div className="checker-section">
      <div className="tracker-header">
        <span className="section-label">Trade Checker <span className="checker-count">({trades.length} open)</span></span>
        <button className="tbl-btn copy-btn" onClick={checkAll}>↻ Check All</button>
      </div>
      <table className="trade-table">
        <thead><tr>
          <th>Symbol</th><th>Dir</th><th>Entry</th><th>Stop</th>
          <th>Target</th><th>Status</th><th>Live P&amp;L</th><th>Last Checked</th><th></th>
        </tr></thead>
        <tbody>
          {trades.map(t => {
            const pnlVal = calcPnl(t);
            const pnlEl = pnlVal != null
              ? <span style={{ color: pnlVal >= 0 ? "var(--long)" : "var(--short)" }}>{pnlVal >= 0 ? "+" : ""}{pnlVal.toFixed(2)}%</span>
              : <span style={{ color: "var(--muted)" }}>—</span>;
            return (
              <tr key={t.trade_id}>
                <td className="mono">{t.symbol}</td>
                <td><Badge value={t.direction?.toUpperCase()} /></td>
                <td className="mono">${fmt(t.entry_price)}</td>
                <td className="mono">${fmt(t.stop)}</td>
                <td className="mono">${fmt(t.target)}</td>
                <td><span style={{ color: t.status === "OPEN" ? "var(--blue)" : "var(--gold)", fontSize: 11 }}>{t.status}</span></td>
                <td className="mono">{pnlEl}</td>
                <td className="mono" style={{ color: "var(--muted)", fontSize: 11 }}>{lastChecked[t.trade_id] || "—"}</td>
                <td>
                  <button
                    className="tbl-btn copy-btn"
                    onClick={() => checkTrade(t)}
                    disabled={!!checking[t.trade_id]}
                  >
                    {checking[t.trade_id] ? "…" : "CHECK"}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div style={{ fontSize: 11, color: "var(--muted)", fontFamily: "var(--font-mono)", marginTop: 6 }}>
        Auto-checks every 30s via background watcher
      </div>
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

function TradeTracker({ result, prefillRef, refreshKey }) {
  const [trades,     setTrades]     = useState([]);
  const [loadError,  setLoadError]  = useState(null);
  const [showForm,   setShowForm]   = useState(false);
  const [copied,     setCopied]     = useState(null);
  const [form,       setForm]       = useState({
    symbol: "", direction: "LONG", entry_price: "", stop: "", target: "", target_2: "",
    trade_type: "scalp", notes: "",
  });

  prefillRef.current = (prefill) => {
    setForm(f => ({ ...f, ...prefill }));
    setShowForm(true);
    setTimeout(() => {
      document.querySelector(".tracker-section")?.scrollIntoView({ behavior: "smooth" });
    }, 100);
  };

  const loadTrades = async () => {
    try {
      const res = await fetch(`${API}/trades?limit=50`);
      if (res.ok) {
        const data = await res.json();
        setTrades(Array.isArray(data) ? data : []);
        setLoadError(null);
      } else {
        setLoadError(`API ${res.status}: ${res.statusText}`);
      }
    } catch (e) {
      setLoadError(`Cannot reach API — ${e.message}`);
    }
  };

  useEffect(() => {
    loadTrades();
    const id = setInterval(loadTrades, 15000);
    return () => clearInterval(id);
  }, []);

  // Reload when parent signals a new trade was added (e.g. TAKE TRADE)
  useEffect(() => { if (refreshKey) loadTrades(); }, [refreshKey]);

  useEffect(() => {
    if (result?.ticker)                        setForm(f => ({ ...f, symbol:      result.ticker }));
    if (result?.trade_plan?.entry_zone?.low)   setForm(f => ({ ...f, entry_price: String(result.trade_plan.entry_zone.low) }));
    if (result?.trade_plan?.stop_loss)         setForm(f => ({ ...f, stop:        String(result.trade_plan.stop_loss) }));
    if (result?.trade_plan?.target_1?.price)   setForm(f => ({ ...f, target:      String(result.trade_plan.target_1.price) }));
    if (result?.trade_plan?.target_2?.price)   setForm(f => ({ ...f, target_2:    String(result.trade_plan.target_2.price) }));
  }, [result]);

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
  const open   = safeTrades.filter(t => ["OPEN","CONFIRMED","TARGET_1_HIT"].includes(t.status));
  const closed = safeTrades.filter(t => !["OPEN","CONFIRMED","TARGET_1_HIT"].includes(t.status));

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

// ── History Tab ───────────────────────────────────────────────────────────────

function HistoryView({ onReanalyze }) {
  const [logs,    setLogs]    = useState([]);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);
  const [filter,  setFilter]  = useState("ALL");

  const loadLogs = () => {
    setLoading(true);
    fetch(`${API}/logs?limit=100`)
      .then(r => r.json())
      .then(data => { setLogs(Array.isArray(data) ? data : []); setLoading(false); })
      .catch(e  => { setError(e.message); setLoading(false); });
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
  const correctN  = resolved.filter(l => l.out_30m_correct === true).length;
  const hitRate   = resolved.length > 0 ? Math.round((correctN / resolved.length) * 100) : null;

  const pnlSpan = (v) => {
    if (v == null) return <span style={{ color: "var(--muted)" }}>—</span>;
    return <span style={{ color: v >= 0 ? "var(--long)" : "var(--short)" }}>{v >= 0 ? "+" : ""}{Number(v).toFixed(2)}%</span>;
  };

  return (
    <div className="history-section">
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div className="history-header" style={{ margin: 0 }}>Analysis History</div>
        <button className="tbl-btn copy-btn" onClick={loadLogs} disabled={loading}>{loading ? "…" : "↻ Refresh"}</button>
      </div>

      {hitRate != null && (
        <div className="hit-rate-bar">
          <span className="hit-rate-label">30m Hit Rate (TRADE verdicts)</span>
          <span className="hit-rate-value" style={{ color: hitRate >= 50 ? "var(--long)" : "var(--short)" }}>
            {hitRate}%
          </span>
          <span className="hit-rate-sub">({correctN}/{resolved.length} resolved)</span>
        </div>
      )}

      <div className="filter-row">
        {["ALL","TRADE","NO_TRADE","Correct","Wrong"].map(f => (
          <button key={f} className={`filter-btn ${filter === f ? "active" : ""}`}
            onClick={() => setFilter(f)}>{f}</button>
        ))}
      </div>

      {error   && <div style={{ color: "var(--short)", fontSize: 12, marginBottom: 12 }}>⚠ {error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div style={{ color: "var(--muted)", fontSize: 13, padding: "24px 0", textAlign: "center" }}>No logs match this filter.</div>
      )}

      {filtered.length > 0 && (
        <table className="trade-table" style={{ fontSize: 11 }}>
          <thead><tr>
            <th>Time</th><th>Symbol</th><th>Verdict</th><th>Dir</th><th>Conf</th>
            <th>Stop</th><th>T1</th><th>T2</th>
            <th>5m P&L</th><th>15m P&L</th><th>30m P&L</th><th>✓?</th><th></th>
          </tr></thead>
          <tbody>
            {filtered.map(log => (
              <tr key={log.id}>
                <td className="mono" style={{ color: "var(--muted)", fontSize: 10 }}>{fmtTime(log.created_at)}</td>
                <td className="mono" style={{ fontWeight: 700 }}>{log.ticker}</td>
                <td><Badge value={log.verdict} /></td>
                <td>{log.direction ? <Badge value={log.direction} /> : <span style={{ color: "var(--muted)" }}>—</span>}</td>
                <td className="mono" style={{ color: "var(--gold)", fontWeight: 700 }}>
                  {log.confidence != null ? `${log.confidence}%` : "—"}
                </td>
                <td className="mono">{log.stop_loss  ? `$${fmt(log.stop_loss)}` : "—"}</td>
                <td className="mono">{log.target_1   ? `$${fmt(log.target_1)}`  : "—"}</td>
                <td className="mono">{log.target_2   ? `$${fmt(log.target_2)}`  : "—"}</td>
                <td className="mono">{pnlSpan(log.out_5m_pnl)}</td>
                <td className="mono">{pnlSpan(log.out_15m_pnl)}</td>
                <td className="mono">{pnlSpan(log.out_30m_pnl)}</td>
                <td style={{ fontSize: 13, textAlign: "center" }}>
                  {log.out_30m_correct == null
                    ? <span style={{ color: "var(--muted)" }}>…</span>
                    : log.out_30m_correct
                      ? <span style={{ color: "var(--long)" }}>✓</span>
                      : <span style={{ color: "var(--short)" }}>✗</span>}
                </td>
                <td>
                  <button className="tbl-btn reanalyze-btn"
                    onClick={() => onReanalyze(log.ticker, log.style === "swing" ? "swing" : "day")}>
                    Re-analyze
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ── Settings Panel ────────────────────────────────────────────────────────────

function SettingsPanel({ analyzeCount = 0 }) {
  const [settings, setSettings] = useState(null);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [aiErr,    setAiErr]    = useState(null);

  const fetchAiStatus = () =>
    fetch(`${API}/ai/status`)
      .then(r => r.json())
      .then(setAiStatus)
      .catch(e => setAiErr(e.message));

  useEffect(() => { fetchAiStatus(); }, [analyzeCount]);

  useEffect(() => {
    fetch(`${API}/settings`)
      .then(r => r.json())
      .then(setSettings)
      .catch(e => setError(e.message));
  }, []);

  const handleSave = async () => {
    try {
      const res = await fetch(`${API}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          moving_averages: settings.moving_averages,
          gap_detection:   settings.gap_detection,
          risk:            settings.risk,
        }),
      });
      if (res.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      } else {
        setError("Save failed");
      }
    } catch (e) {
      setError(e.message);
    }
  };

  const setMA = (key, field, value) => {
    setSettings(s => ({
      ...s,
      moving_averages: {
        ...s.moving_averages,
        [key]: { ...s.moving_averages[key], [field]: field === "period" ? parseInt(value) || 0 : value },
      },
    }));
  };

  const setGap = (field, value) => {
    setSettings(s => ({
      ...s,
      gap_detection: {
        ...s.gap_detection,
        [field]: field === "atr_multiplier"
          ? parseFloat(value) || 1.0
          : value.split(",").map(v => v.trim().toUpperCase()).filter(Boolean),
      },
    }));
  };

  const setRisk = (field, value) => {
    setSettings(s => ({
      ...s,
      risk: { ...s.risk, [field]: parseFloat(value) || 0 },
    }));
  };

  if (!settings) return (
    <div className="settings-panel">
      <div style={{ color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
        {error ? `⚠ ${error}` : "Loading settings…"}
      </div>
    </div>
  );

  const mas = Object.entries(settings.moving_averages || {})
    .filter(([k]) => !k.startsWith("_"))
    .sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="settings-panel">

      {/* AI Engine */}
      <div className="settings-section">
        <div className="settings-section-title">AI Engine</div>
        {aiStatus ? (
          <>
            <div className="settings-field">
              <span className="settings-label">Status</span>
              <button
                onClick={() =>
                  fetch(`${API}/ai/toggle`, { method: "POST" })
                    .then(r => r.json()).then(setAiStatus).catch(e => setAiErr(e.message))
                }
                style={{
                  background: aiStatus.ai_enabled ? "rgba(0,228,154,0.12)" : "rgba(255,80,80,0.12)",
                  color:      aiStatus.ai_enabled ? "var(--long)" : "var(--short)",
                  border:     `1px solid ${aiStatus.ai_enabled ? "var(--long)" : "var(--short)"}`,
                  borderRadius: 4, padding: "5px 14px", cursor: "pointer",
                  fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: "0.06em",
                }}
              >
                {aiStatus.ai_enabled ? "AI LIVE \u25B6" : "AI PAUSED \u25A0"}
              </button>
            </div>
            <div className="settings-field">
              <span className="settings-label">Today</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)" }}>
                {(aiStatus.ai_calls?.daily_count ?? 0).toLocaleString()} calls
              </span>
            </div>
            <div className="settings-field">
              <span className="settings-label">Session</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)", marginRight: 10 }}>
                {(aiStatus.ai_calls?.session_count ?? 0).toLocaleString()} calls
              </span>
              <button
                onClick={() =>
                  fetch(`${API}/ai/reset-counter`, { method: "POST" })
                    .then(r => r.json())
                    .then(d => setAiStatus(s => ({ ...s, ai_calls: d.ai_calls })))
                    .catch(e => setAiErr(e.message))
                }
                style={{
                  background: "rgba(255,168,0,0.12)", color: "#ffa800",
                  border: "1px solid #ffa800", borderRadius: 4,
                  padding: "3px 10px", cursor: "pointer",
                  fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.06em",
                }}
              >
                RESET
              </button>
            </div>
            <div className="settings-field">
              <span className="settings-label">All Time</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)" }}>
                {(aiStatus.ai_calls?.total_all_time ?? 0).toLocaleString()} calls
              </span>
            </div>
            {aiErr && <div style={{ color: "var(--short)", fontFamily: "var(--font-mono)", fontSize: 10, marginTop: 4 }}>⚠ {aiErr}</div>}
          </>
        ) : (
          <div style={{ color: "var(--muted)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
            {aiErr ? `⚠ ${aiErr}` : "Loading…"}
          </div>
        )}
      </div>

      {/* Moving Averages */}
      <div className="settings-section">
        <div className="settings-section-title">Moving Averages</div>
        {mas.map(([key, ma]) => (
          <div key={key} className="settings-field">
            <span className="settings-label">{key.toUpperCase()}</span>
            <input
              className="settings-input" type="number" min="1" max="500"
              value={ma.period} style={{ width: 70 }}
              onChange={e => setMA(key, "period", e.target.value)}
            />
            <select className="settings-input" style={{ width: 80 }} value={ma.type}
              onChange={e => setMA(key, "type", e.target.value)}>
              <option value="SMA">SMA</option>
              <option value="EMA">EMA</option>
            </select>
          </div>
        ))}
      </div>

      {/* Gap Detection */}
      <div className="settings-section">
        <div className="settings-section-title">Gap Detection</div>
        <div className="settings-field">
          <span className="settings-label">ATR Multiplier</span>
          <input
            className="settings-input" type="number" min="0.1" max="5" step="0.1"
            value={settings.gap_detection?.atr_multiplier ?? 1.0} style={{ width: 80 }}
            onChange={e => setGap("atr_multiplier", e.target.value)}
          />
        </div>
        <div className="settings-field">
          <span className="settings-label">Excluded Symbols</span>
          <input
            className="settings-input"
            value={(settings.gap_detection?.excluded_symbols || []).join(", ")} style={{ width: 260 }}
            onChange={e => setGap("excluded_symbols", e.target.value)}
          />
        </div>
      </div>

      {/* Risk */}
      <div className="settings-section">
        <div className="settings-section-title">Risk</div>
        <div className="settings-field">
          <span className="settings-label">Account Size ($)</span>
          <input
            className="settings-input" type="number" min="1000" step="1000"
            value={settings.risk?.account_size ?? 25000} style={{ width: 120 }}
            onChange={e => setRisk("account_size", e.target.value)}
          />
        </div>
        <div className="settings-field">
          <span className="settings-label">Risk Per Trade (%)</span>
          <input
            className="settings-input" type="number" min="0.1" max="10" step="0.1"
            value={settings.risk?.risk_percent ?? 2.0} style={{ width: 80 }}
            onChange={e => setRisk("risk_percent", e.target.value)}
          />
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <button className="save-btn" onClick={handleSave}>Save Settings</button>
        {saved  && <span className="saved-indicator">Saved ✓</span>}
        {error  && <span style={{ color: "var(--short)", fontFamily: "var(--font-mono)", fontSize: 11 }}>⚠ {error}</span>}
      </div>
    </div>
  );
}


// ── Main App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [activeTab,    setActiveTab]    = useState("analyze");
  const [ticker,       setTicker]       = useState("");
  const [loading,      setLoading]      = useState(false);
  const [result,       setResult]       = useState(null);
  const [error,        setError]        = useState(null);
  const [tradeType,    setTradeType]    = useState("day");
  const [refreshKey,   setRefreshKey]   = useState(0);
  const [analyzeCount, setAnalyzeCount] = useState(0);
  const prefillRef = useRef(null);

  // Core analyze function — accepts explicit params to avoid stale closure
  const doAnalyze = async (t, tt) => {
    if (!t.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${API}/analyze`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ ticker: t.trim().toUpperCase(), trade_type: tt }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Request failed");
      }
      setResult(await res.json());
      setAnalyzeCount(c => c + 1);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const analyze    = () => doAnalyze(ticker, tradeType);
  const reEvaluate = () => doAnalyze(ticker, tradeType);
  const onKey      = (e) => { if (e.key === "Enter") analyze(); };

  const handleAddTrade = () => {
    if (!result) return;
    const prefill = {
      symbol:      result.ticker || "",
      entry_price: result.price ? String(result.price) : (result.trade_plan?.entry_zone?.low ? String(result.trade_plan.entry_zone.low) : ""),
      stop:        result.trade_plan?.stop_loss ? String(result.trade_plan.stop_loss) : "",
      target:      result.trade_plan?.target_1?.price ? String(result.trade_plan.target_1.price) : "",
      target_2:    result.trade_plan?.target_2?.price ? String(result.trade_plan.target_2.price) : "",
      direction:   result.trade_plan?.direction === "SHORT" ? "SHORT" : "LONG",
      trade_type:  tradeType === "swing" ? "swing" : "scalp",
    };
    prefillRef.current?.(prefill);
  };

  const handleTakeTrade = async (params) => {
    const qRes = await fetch(`${API}/quote/${params.symbol}`);
    if (!qRes.ok) throw new Error("Quote unavailable");
    const { price } = await qRes.json();
    const res = await fetch(`${API}/trades`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...params, entry_price: price }),
    });
    if (!res.ok) throw new Error("Trade submission failed");
    setRefreshKey(k => k + 1);
    // Scroll to tracker section after a brief delay
    setTimeout(() => {
      document.querySelector(".tracker-section")?.scrollIntoView({ behavior: "smooth" });
    }, 150);
  };

  const handleReanalyze = (logTicker, logTradeType) => {
    const t  = logTicker.toUpperCase();
    const tt = logTradeType || "day";
    setTicker(t);
    setTradeType(tt);
    setActiveTab("analyze");
    doAnalyze(t, tt);
  };

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
        .logo {
          font-size: 11px; font-family: var(--font-mono);
          color: var(--text); letter-spacing: 0.12em;
          text-transform: uppercase; font-weight: 700;
        }

        .nav-controls { margin-left: auto; display: flex; align-items: center; gap: 8px; }

        .nav-btn {
          font-size: 10px; font-family: var(--font-mono); font-weight: 700;
          background: #1a1e2a; border: 1px solid var(--border);
          color: var(--muted); padding: 5px 12px; border-radius: 3px;
          cursor: pointer; letter-spacing: 0.08em; text-transform: uppercase;
          transition: all 0.15s;
        }
        .nav-btn.active { color: var(--text); border-color: rgba(77,159,255,0.5); background: rgba(77,159,255,0.08); }
        .nav-btn:hover  { color: var(--text); }

        /* ── Market bar ── */
        .market-bar {
          display: flex; gap: 24px; padding: 10px 32px;
          border-bottom: 1px solid var(--border);
          font-family: var(--font-mono); font-size: 12px;
          background: #0d0f14;
        }
        .mkt-item { color: var(--muted); }
        .mkt-label { color: var(--text); font-weight: 700; }
        .mkt-item .up   { color: var(--long); }
        .mkt-item .dn   { color: var(--short); }
        .mkt-item .vix  { color: var(--gold); }
        .mkt-item .mkt-price { color: var(--text); }

        /* ── Main ── */
        .main { max-width: 900px; margin: 0 auto; padding: 40px 24px; }

        /* ── Search row (25% smaller) ── */
        .search-row {
          display: flex; gap: 9px; margin-bottom: 40px; align-items: center;
        }
        .ticker-input {
          flex: 1; background: var(--surface); border: 1px solid var(--border);
          color: var(--text); font-family: var(--font-mono); font-size: 16px;
          font-weight: 700; padding: 10px 15px; border-radius: 6px;
          text-transform: uppercase; letter-spacing: 0.08em;
          outline: none; transition: border-color 0.2s;
        }
        .ticker-input::placeholder { color: var(--muted); }
        .ticker-input:focus { border-color: var(--blue); }

        .tradetype-select {
          background: var(--surface); border: 1px solid var(--border);
          color: var(--text); font-family: var(--font-mono); font-size: 11px;
          font-weight: 700; padding: 10px 12px; border-radius: 6px;
          cursor: pointer; text-transform: uppercase; letter-spacing: 0.06em;
          white-space: nowrap;
        }
        .tradetype-select:focus { outline: none; border-color: var(--blue); }
        .tradetype-select option { background: #1a1e2a; }

        .analyze-btn {
          background: var(--blue); color: #fff; border: none;
          font-family: var(--font-ui); font-size: 11px; font-weight: 600;
          padding: 10px 24px; border-radius: 6px; cursor: pointer;
          letter-spacing: 0.05em; transition: opacity 0.2s; white-space: nowrap;
        }
        .analyze-btn:disabled { opacity: 0.4; cursor: default; }
        .analyze-btn:hover:not(:disabled) { opacity: 0.85; }

        .reeval-btn {
          background: rgba(77,159,255,0.12); color: var(--blue);
          border: 1px solid rgba(77,159,255,0.35);
          font-family: var(--font-ui); font-size: 10px; font-weight: 600;
          padding: 10px 15px; border-radius: 6px; cursor: pointer;
          letter-spacing: 0.04em; transition: opacity 0.2s; white-space: nowrap;
        }
        .reeval-btn:hover { opacity: 0.8; }

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
        .plan-add-btn { margin-left: auto; }

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

        /* ── Tomorrow's Setup ── */
        .tomorrow-setup {
          background: rgba(245,200,66,0.04); border: 1px solid rgba(245,200,66,0.2);
          border-radius: 6px; padding: 16px; margin-top: 4px; margin-bottom: 16px;
        }
        .tomorrow-header {
          font-size: 10px; font-family: var(--font-mono); font-weight: 700;
          color: var(--gold); text-transform: uppercase; letter-spacing: 0.12em;
          margin-bottom: 12px;
        }
        .tomorrow-grid {
          display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
          margin-bottom: 12px;
        }
        .tomorrow-block .t-label {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px;
        }
        .tomorrow-block .t-value {
          font-size: 14px; font-family: var(--font-mono); font-weight: 700; color: var(--text);
        }
        .void-badge {
          font-size: 11px; font-family: var(--font-mono);
          background: rgba(255,153,0,0.08); border: 1px solid rgba(255,153,0,0.3);
          color: #ff9900; padding: 4px 10px; border-radius: 4px; display: inline-block;
        }

        .plan-reasoning, .position-notes {
          border-top: 1px solid var(--border); padding-top: 16px; margin-top: 4px;
        }
        .reasoning-label {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.1em; display: block;
          margin-bottom: 8px;
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
        .agent-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent, var(--blue)); flex-shrink: 0; }
        .agent-title { font-size: 13px; font-family: var(--font-mono); font-weight: 700; color: #fff; text-transform: uppercase; letter-spacing: 0.06em; }
        .agent-meta { font-size: 13px; color: var(--muted); margin-top: 8px; }
        .flag-list { margin-top: 8px; padding-left: 0; list-style: none; }
        .flag-list li { font-size: 13px; color: var(--gold); margin-bottom: 4px; }

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

        /* Confidence — gold + bold everywhere */
        .confidence { font-size: 13px; font-family: var(--font-mono); color: var(--gold); font-weight: 700; }
        .confidence.large { font-size: 14px; color: var(--gold); }

        /* ── Bullet list (agent + synthesis reasoning) ── */
        .bullet-list { list-style: none; padding: 0; margin: 0; }
        .bullet-list li {
          font-size: 14px; line-height: 1.7; color: var(--text);
          padding-left: 4px;
        }
        .plan-reasoning .bullet-list li { font-size: 14px; color: var(--text); }

        /* ── Trade Checker ── */
        .checker-section {
          margin-top: 40px; border-top: 1px solid var(--border); padding-top: 28px;
          margin-bottom: 0;
        }
        .checker-count { color: var(--blue); }

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
        .tbl-btn:disabled { opacity: 0.4; cursor: default; }
        .copy-btn       { background: rgba(77,159,255,0.15); color: var(--blue); border: 1px solid rgba(77,159,255,0.3); }
        .close-btn      { background: rgba(255,77,109,0.12); color: var(--short); border: 1px solid rgba(255,77,109,0.3); }
        .add-btn        { background: rgba(0,228,154,0.12);  color: var(--long);  border: 1px solid rgba(0,228,154,0.3); }
        .reanalyze-btn  { background: rgba(77,159,255,0.1);  color: var(--blue);  border: 1px solid rgba(77,159,255,0.3); }

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
          background: rgba(0,228,154,0.15); color: var(--long);
          border: 1px solid rgba(0,228,154,0.4);
          font-family: var(--font-mono); font-size: 11px; font-weight: 700;
          padding: 6px 16px; border-radius: 4px; cursor: pointer;
          letter-spacing: 0.08em; transition: opacity 0.15s, background 0.2s;
          white-space: nowrap;
        }
        .take-trade-btn:hover { opacity: 0.85; }
        .take-trade-btn.taken { background: rgba(0,228,154,0.25); cursor: default; }
        .take-trade-btn:disabled { opacity: 0.4; cursor: default; }

        /* ── History ── */
        .history-section { padding: 32px 0; }
        .history-header {
          font-size: 10px; font-family: var(--font-mono); color: var(--muted);
          text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 16px;
        }

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

        /* ── Settings ── */
        .settings-panel { padding: 32px 0; }
        .settings-section { margin-bottom: 28px; }
        .settings-section-title {
          font-size: 11px; font-family: var(--font-mono); color: var(--text);
          text-transform: uppercase; letter-spacing: 0.1em;
          border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 14px;
        }
        .settings-field { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
        .settings-label { font-size: 11px; font-family: var(--font-mono); color: var(--muted); min-width: 150px; }
        .settings-input {
          background: var(--bg); border: 1px solid var(--border);
          color: var(--text); border-radius: 4px; padding: 6px 10px;
          font-family: var(--font-mono); font-size: 12px;
        }
        .settings-input:focus { outline: none; border-color: var(--blue); }
        .save-btn {
          background: rgba(0,228,154,0.12); color: var(--long);
          border: 1px solid rgba(0,228,154,0.3);
          font-family: var(--font-mono); font-size: 11px; font-weight: 700;
          padding: 8px 20px; border-radius: 4px; cursor: pointer;
        }
        .save-btn:hover { opacity: 0.8; }
        .saved-indicator { color: var(--long); font-family: var(--font-mono); font-size: 11px; }

        @media (max-width: 640px) {
          .plan-grid { grid-template-columns: repeat(2, 1fr); }
          .agents-grid { grid-template-columns: 1fr; }
          .trade-table { font-size: 11px; }
          .tomorrow-grid { grid-template-columns: repeat(2, 1fr); }
        }
      `}</style>

      <div className="header">
        <div className="logo">TRADE CHECKER</div>
        <div className="nav-controls">
          {["analyze", "history", "settings"].map(tab => (
            <button
              key={tab}
              className={`nav-btn ${activeTab === tab ? "active" : ""}`}
              onClick={() => setActiveTab(tab)}
            >
              {tab.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {result && activeTab === "analyze" && <MarketBar ctx={result.market_context} />}

      <div className="main">
        {/* ── Analyze Tab ── */}
        {activeTab === "analyze" && (
          <>
            <div className="search-row">
              <input
                className="ticker-input"
                placeholder="AAPL"
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                onKeyDown={onKey}
                maxLength={10}
              />
              <select
                className="tradetype-select"
                value={tradeType}
                onChange={e => setTradeType(e.target.value)}
              >
                <option value="day">Day Trade</option>
                <option value="swing">Swing Trade</option>
              </select>
              <button className="analyze-btn" onClick={analyze} disabled={loading || !ticker.trim()}>
                {loading ? "Analyzing…" : "Analyze"}
              </button>
              {result && !loading && (
                <button className="reeval-btn" onClick={reEvaluate} disabled={loading}>
                  ↻ RE-EVALUATE
                </button>
              )}
            </div>

            {loading && (
              <div className="loading-state">
                <div className="spinner" />
                Running {tradeType === "swing" ? "swing" : "day"} trade agents in parallel…
              </div>
            )}

            {error && <div className="error-box">⚠ {error}</div>}

            {result && (
              <>
                <TradePlan
                  plan={result.trade_plan}
                  ticker={result.ticker}
                  price={result.price}
                  onAddTrade={handleAddTrade}
                  onTakeTrade={handleTakeTrade}
                  tradeType={tradeType}
                  agentVerdicts={result.agent_verdicts}
                />

                <div className="agents-section">
                  <span className="agents-label">Agent Verdicts</span>
                  <div className="agents-grid">
                    <AgentCard title="Technical" data={result.agent_verdicts?.technical} color="var(--blue)" />
                    <AgentCard title="Macro"     data={result.agent_verdicts?.macro}     color="var(--gold)" />
                    <AgentCard title="Wild Card" data={result.agent_verdicts?.wildcard}  color="var(--short)" />
                  </div>
                </div>
              </>
            )}

            <TrackerErrorBoundary>
              <TradeChecker />
            </TrackerErrorBoundary>

            <TrackerErrorBoundary>
              <TradeTracker result={result} prefillRef={prefillRef} refreshKey={refreshKey} />
            </TrackerErrorBoundary>
          </>
        )}

        {/* ── History Tab ── */}
        {activeTab === "history" && (
          <HistoryView onReanalyze={handleReanalyze} />
        )}

        {/* ── Settings Tab ── */}
        {activeTab === "settings" && (
          <SettingsPanel analyzeCount={analyzeCount} />
        )}
      </div>
    </>
  );
}
