"""Paper trading engine — simulated orders over the live market data feed.

PAPER invariant: nothing in this package may send, modify or cancel a broker
order. The only market interaction allowed is *reading* quotes through the
existing ``data_feed`` providers (which connect ``readonly=True``). A test
(``tests/test_paper_no_broker_writes.py``) enforces that no order-execution
symbol from ib_insync is ever imported here.
"""
