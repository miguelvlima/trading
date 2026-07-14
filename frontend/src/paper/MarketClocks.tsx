import { useEffect, useState } from "react";

import {
  fmtClock,
  fmtDay,
  MARKETS,
  marketStatus,
  sessionsLabelLocal,
  sessionsLabelMarket,
  STATUS_LABEL,
} from "./marketHours";

// Dual wall clock (viewer-local + New York) for the cockpit's top bar.
// Hovering (or focusing, for keyboard users) opens the world-markets panel.
export function MarketClocks() {
  const [now, setNow] = useState(() => new Date());
  const [panelOpen, setPanelOpen] = useState(false);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <div
      className="pp-clocks"
      tabIndex={0}
      onMouseEnter={() => setPanelOpen(true)}
      onMouseLeave={() => setPanelOpen(false)}
      onFocus={() => setPanelOpen(true)}
      onBlur={() => setPanelOpen(false)}
    >
      <span className="pp-clock">
        <span className="pp-clock-city">Local</span>
        <span className="pp-clock-time">{fmtClock(now)}</span>
        <span className="pp-clock-date">{fmtDay(now)}</span>
      </span>
      <span className="pp-clock">
        <span className="pp-clock-city">Nova Iorque</span>
        <span className="pp-clock-time">{fmtClock(now, "America/New_York")}</span>
        <span className="pp-clock-date">{fmtDay(now, "America/New_York")}</span>
      </span>
      {panelOpen && (
        <div className="pp-clock-panel">
          <table className="pp-clock-table">
            <thead>
              <tr>
                <th>Mercado</th>
                <th>Hora lá</th>
                <th>Sessão (lá)</th>
                <th>Na tua hora</th>
                <th>Estado</th>
              </tr>
            </thead>
            <tbody>
              {MARKETS.map((market) => {
                const status = marketStatus(market, now);
                return (
                  <tr key={market.id}>
                    <td>
                      <b>{market.city}</b>{" "}
                      <span className="pp-muted">{market.exchange}</span>
                    </td>
                    <td className="pp-clock-num">{fmtClock(now, market.tz)}</td>
                    <td className="pp-clock-num">{sessionsLabelMarket(market)}</td>
                    <td className="pp-clock-num">{sessionsLabelLocal(market, now)}</td>
                    <td>
                      <span className={`pp-clock-status pp-clock-status-${status}`}>
                        {STATUS_LABEL[status]}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="pp-clock-note pp-muted">
            Horário regular, sem feriados das bolsas.
          </p>
        </div>
      )}
    </div>
  );
}
