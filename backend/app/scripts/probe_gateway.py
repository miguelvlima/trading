"""Empirical IB Gateway probe for the paper-trading engine design (Phase 0).

Read-only diagnostic: connects to the Gateway with ``readonly=True``, subscribes
to market data for a few symbols and measures what actually arrives — which tick
fields are populated, tick frequency, broker-vs-local timestamp skew, spreads,
and reconnect behaviour. It NEVER places, modifies or cancels orders; the only
API calls used are connection, account metadata and ``reqMktData``.

Run from ``backend/``:

    .venv/Scripts/python.exe -m app.scripts.probe_gateway --duration 60

Output: human-readable summary on stderr, JSON report on stdout (redirect to a
file to share). Findings feed ``docs/gateway-findings.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from typing import Any

MARKET_DATA_TYPE_LABEL = {1: "REALTIME", 2: "FROZEN", 3: "DELAYED", 4: "DELAYED_FROZEN"}


def _num(value: Any) -> float | None:
    """IBKR reports unset numeric fields as nan; normalise those to None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def _stats(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    return {
        "count": len(values),
        "min": round(ordered[0], 6),
        "p50": round(statistics.median(ordered), 6),
        "p90": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], 6),
        "max": round(ordered[-1], 6),
        "mean": round(statistics.fmean(ordered), 6),
    }


def probe(
    host: str,
    port: int,
    client_id: int,
    symbols: list[str],
    duration: float,
    md_type: int = 1,
) -> dict:
    from ib_insync import IB, Stock, util

    util.patchAsyncio()
    report: dict[str, Any] = {
        "probe_started_utc": datetime.now(UTC).isoformat(),
        "host": host,
        "port": port,
        "client_id": client_id,
        "symbols": symbols,
        "duration_seconds": duration,
        "requested_market_data_type": MARKET_DATA_TYPE_LABEL.get(md_type, md_type),
        "errors": [],
    }

    ib = IB()

    def on_error(reqId, errorCode, errorString, contract=None) -> None:
        report["errors"].append(
            {
                "t_utc": datetime.now(UTC).isoformat(),
                "req_id": reqId,
                "code": errorCode,
                "message": errorString,
                "contract": getattr(contract, "symbol", None),
            }
        )

    ib.errorEvent += on_error

    t0 = time.monotonic()
    ib.connect(host, port, clientId=client_id, timeout=15, readonly=True)
    connect_seconds = time.monotonic() - t0

    accounts = ib.managedAccounts()
    report["connection"] = {
        "connect_seconds": round(connect_seconds, 3),
        "server_version": ib.client.serverVersion(),
        "tws_connection_time": str(ib.reqCurrentTime()),
        "managed_accounts": accounts,
        # Paper accounts are prefixed with "D" (e.g. DU1234567). This matters:
        # the engine design assumes a paper/read-only Gateway.
        "all_accounts_look_paper": bool(accounts) and all(a.startswith("D") for a in accounts),
        "readonly": True,
    }

    # With type 1 (live) and no entitlement the Gateway emits error 10089 and
    # sends NOTHING; type 3 asks for delayed data explicitly, matching the
    # production setting ``ibkr_market_data_type=3``.
    ib.reqMarketDataType(md_type)

    tickers = {}
    samples: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    md_types: dict[str, set[int]] = {s: set() for s in symbols}

    for symbol in symbols:
        contract = Stock(symbol, "SMART", "USD")
        tickers[symbol] = ib.reqMktData(contract, "", False, False)

    def on_pending(pending) -> None:
        now_utc = datetime.now(UTC)
        for ticker in pending:
            symbol = getattr(ticker.contract, "symbol", None)
            if symbol not in samples:
                continue
            md_code = getattr(ticker, "marketDataType", None)
            if isinstance(md_code, int):
                md_types[symbol].add(md_code)
            broker_time = getattr(ticker, "time", None)
            samples[symbol].append(
                {
                    "local_utc": now_utc,
                    "broker_time": broker_time,
                    "last": _num(ticker.last),
                    "bid": _num(ticker.bid),
                    "ask": _num(ticker.ask),
                    "bid_size": _num(ticker.bidSize),
                    "ask_size": _num(ticker.askSize),
                    "last_size": _num(ticker.lastSize),
                    "volume": _num(ticker.volume),
                    "halted": _num(getattr(ticker, "halted", None)),
                }
            )

    ib.pendingTickersEvent += on_pending
    print(f"[probe] collecting ticks for {duration:.0f}s ...", file=sys.stderr)
    ib.sleep(duration)
    ib.pendingTickersEvent -= on_pending

    per_symbol: dict[str, Any] = {}
    for symbol, rows in samples.items():
        inter_arrival = [
            (b["local_utc"] - a["local_utc"]).total_seconds()
            for a, b in zip(rows, rows[1:], strict=False)
        ]
        latencies = [
            (r["local_utc"] - r["broker_time"]).total_seconds()
            for r in rows
            if isinstance(r["broker_time"], datetime) and r["broker_time"].tzinfo is not None
        ]
        spreads_bps = []
        for r in rows:
            bid, ask = r["bid"], r["ask"]
            if bid and ask and ask >= bid > 0:
                spreads_bps.append((ask - bid) / ((ask + bid) / 2) * 10_000)
        n = len(rows)
        per_symbol[symbol] = {
            "updates": n,
            "updates_per_second": round(n / duration, 3),
            "market_data_types": sorted(
                MARKET_DATA_TYPE_LABEL.get(c, str(c)) for c in md_types[symbol]
            ),
            "field_presence_pct": {
                f: _pct(sum(1 for r in rows if r[f] is not None), n)
                for f in ("last", "bid", "ask", "bid_size", "ask_size", "last_size", "volume")
            },
            "inter_arrival_seconds": _stats(inter_arrival),
            "broker_vs_local_latency_seconds": _stats(latencies),
            "spread_bps": _stats(spreads_bps),
            "last_snapshot": {
                k: (v.isoformat() if isinstance(v, datetime) else v)
                for k, v in rows[-1].items()
            }
            if rows
            else None,
        }
    report["per_symbol"] = per_symbol

    for ticker in tickers.values():
        ib.cancelMktData(ticker.contract)

    # Reconnect drill: how long a clean disconnect -> reconnect cycle takes.
    print("[probe] reconnect drill ...", file=sys.stderr)
    ib.disconnect()
    time.sleep(1.0)
    t1 = time.monotonic()
    try:
        ib.connect(host, port, clientId=client_id, timeout=15, readonly=True)
        report["reconnect"] = {"ok": True, "seconds": round(time.monotonic() - t1, 3)}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        report["reconnect"] = {"ok": False, "error": str(exc)}
    finally:
        if ib.isConnected():
            ib.disconnect()

    report["probe_finished_utc"] = datetime.now(UTC).isoformat()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4001)
    parser.add_argument("--client-id", type=int, default=97)
    parser.add_argument("--symbols", default="AAPL,MSFT,NVDA,SPY")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument(
        "--md-type",
        type=int,
        default=3,
        choices=(1, 2, 3, 4),
        help="reqMarketDataType: 1=live, 2=frozen, 3=delayed, 4=delayed-frozen",
    )
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    report = probe(args.host, args.port, args.client_id, symbols, args.duration, args.md_type)
    json.dump(report, sys.stdout, indent=2, default=str)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
