"""Static guard for the PAPER invariant.

Nothing under ``app/services/paper_trading`` or the paper API routes may touch
order-execution APIs: the engine simulates fills locally and only ever *reads*
market data. If this test fails, someone wired real order flow into the paper
phase — that is a design violation, not a missing allowlist entry.
"""

from __future__ import annotations

from pathlib import Path

PAPER_SOURCES = [
    Path("app/services/paper_trading"),
    Path("app/api/routes/paper_trading.py"),
    Path("app/api/routes/paper_ws.py"),
]

# ib_insync / TWS order-execution surface (and generic broker order verbs).
FORBIDDEN_TOKENS = [
    "placeOrder",
    "cancelOrder",
    "whatIfOrder",
    "bracketOrder",
    "MarketOrder(",
    "LimitOrder(",
    "StopOrder(",
    "StopLimitOrder(",
    "from ib_insync import Order",
    "ib_insync.order",
    "reqGlobalCancel",
]


def _paper_files() -> list[Path]:
    backend_root = Path(__file__).resolve().parent.parent
    files: list[Path] = []
    for source in PAPER_SOURCES:
        target = backend_root / source
        if target.is_dir():
            files.extend(sorted(target.rglob("*.py")))
        elif target.exists():
            files.append(target)
    return files


def test_paper_sources_exist() -> None:
    files = _paper_files()
    assert len(files) >= 8, f"expected the paper trading package, found {files}"


def test_no_order_execution_symbols_in_paper_code() -> None:
    offenders: list[str] = []
    for path in _paper_files():
        content = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in content:
                offenders.append(f"{path.name}: {token}")
    assert not offenders, f"PAPER invariant violated: {offenders}"
