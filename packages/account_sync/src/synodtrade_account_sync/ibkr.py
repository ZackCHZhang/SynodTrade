"""Reads an IBKR account through `ib_async`: open and completed orders, executions, the
account summary and positions. Never places, modifies or cancels anything.

It uses its own API connection (account client_id + 4; market data +0, trading +1, news +2,
scanner +3), so a background synchronisation can run while a pipeline is running.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from decimal import Decimal
from typing import Any

from ib_async import IB, ExecutionFilter, StartupFetch, Trade
from ib_async import Fill as IBFill

from synodtrade_account_sync.snapshot import BrokerExecution, BrokerOrder, BrokerSnapshot
from synodtrade_core.config import AccountConfig
from synodtrade_core.logging import get_logger
from synodtrade_core.timeutil import utcnow
from synodtrade_market_data import IBKRMarketDataProvider
from synodtrade_trading.ibkr import to_status

log = get_logger(__name__)

CLIENT_ID_OFFSET = 4
_UNSET = 1e300  # ib_async marks unset doubles with sys.float_info.max


class AccountSyncError(RuntimeError):
    pass


def _dec(value: float | Decimal | None) -> Decimal:
    if value is None or value >= _UNSET:
        return Decimal(0)
    return Decimal(str(value))


def _side(action: str) -> str:
    return "buy" if action.upper() in ("BUY", "BOT") else "sell"


def order_from_trade(trade: Trade, *, is_open: bool) -> BrokerOrder:
    order, st = trade.order, trade.orderStatus
    # completed orders carry no filled quantity in their status, only on the order
    filled = max(_dec(st.filled), _dec(getattr(order, "filledQuantity", None)))
    avg = _dec(st.avgFillPrice)
    limit = _dec(order.lmtPrice) if order.orderType == "LMT" else Decimal(0)
    return BrokerOrder(
        ref=order.orderRef or "",
        symbol=trade.contract.symbol,
        side=_side(order.action),
        quantity=_dec(order.totalQuantity),
        status=to_status(st.status, filled),
        broker_status=st.status,
        filled=filled,
        avg_fill_price=avg if avg > 0 and filled > 0 else None,
        limit_price=limit or None,
        perm_id=order.permId or 0,
        order_id=order.orderId or 0,
        open=is_open,
        message="; ".join(e.message for e in trade.log if e.message)[-500:] or None,
    )


def execution_from_fill(fill: IBFill) -> BrokerExecution:
    ex, report = fill.execution, fill.commissionReport
    has_report = bool(report and report.execId == ex.execId)
    return BrokerExecution(
        exec_id=ex.execId,
        ref=ex.orderRef or "",
        symbol=fill.contract.symbol,
        side=_side(ex.side),
        shares=_dec(ex.shares),
        price=_dec(ex.price),
        ts=fill.time or utcnow(),
        commission=_dec(report.commission) if has_report else None,
    )


class IBKRAccountReader:
    def __init__(
        self,
        *,
        account_id: str,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 21,
        base_currency: str = "USD",
        connect_timeout_s: float = 10.0,
        commission_wait_s: float = 3.0,
        ib: IB | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.account_id = account_id
        self.host, self.port, self.client_id = host, port, client_id
        self.base_currency = base_currency
        self.connect_timeout_s = connect_timeout_s
        self.commission_wait_s = commission_wait_s
        self._ib = ib or IB()
        self._sleep = sleep

    @classmethod
    def from_account(cls, account: AccountConfig, **kwargs: Any) -> IBKRAccountReader:
        return cls(
            account_id=account.account_id,
            host=account.host,
            port=account.port,
            client_id=account.client_id + CLIENT_ID_OFFSET,
            base_currency=account.base_currency,
            **kwargs,
        )

    async def connect(self) -> None:
        if self._ib.isConnected():
            return
        # not read-only: IBKR refuses execution requests on read-only connections; this
        # class still never sends an order. Orders and executions are requested explicitly.
        await self._ib.connectAsync(
            self.host,
            self.port,
            clientId=self.client_id,
            timeout=self.connect_timeout_s,
            fetchFields=StartupFetch.POSITIONS,
        )
        managed = self._ib.managedAccounts()
        if self.account_id not in managed:
            self._ib.disconnect()
            raise AccountSyncError(f"account {self.account_id} is not managed by this gateway")
        log.info("account_sync.connected", account=self.account_id, client_id=self.client_id)

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    def _ours(self, account: str) -> bool:
        return not account or account == self.account_id

    async def _executions(self) -> list[IBFill]:
        fills = [
            f
            for f in await self._ib.reqExecutionsAsync(ExecutionFilter(acctCode=self.account_id))
            if self._ours(f.execution.acctNumber)
        ]
        # commission reports follow the executions; give them a moment to arrive
        waited = 0.0
        while waited < self.commission_wait_s and any(
            not (f.commissionReport and f.commissionReport.execId == f.execution.execId)
            for f in fills
        ):
            await self._sleep(0.25)
            waited += 0.25
        return fills

    async def snapshot(self, *, account: bool = True) -> BrokerSnapshot:
        if not self._ib.isConnected():
            raise AccountSyncError(f"not connected to IBKR at {self.host}:{self.port}")
        fetched_at = utcnow()
        open_trades = [
            t for t in await self._ib.reqAllOpenOrdersAsync() if self._ours(t.order.account)
        ]
        completed = [
            t
            for t in await self._ib.reqCompletedOrdersAsync(apiOnly=False)
            if self._ours(t.order.account)
        ]
        fills = await self._executions()

        snap = BrokerSnapshot(account_id=self.account_id, fetched_at=fetched_at)
        open_orders = [order_from_trade(t, is_open=not t.isDone()) for t in open_trades]
        snap.open_orders = [o for o in open_orders if o.open]
        orders = [*(order_from_trade(t, is_open=False) for t in completed), *open_orders]
        for order in orders:  # open orders last: they are the most recent state
            if order.ref:
                snap.orders[order.ref] = order
        for fill in _dedupe(fills):
            execution = execution_from_fill(fill)
            if execution.ref:
                snap.executions.setdefault(execution.ref, []).append(execution)

        if account:
            try:
                data = await IBKRMarketDataProvider(
                    host=self.host,
                    port=self.port,
                    client_id=self.client_id,
                    base_currency=self.base_currency,
                    ib=self._ib,
                ).fetch_account(self.account_id)
                snap.account, snap.positions = data.account, list(data.positions)
            except Exception as exc:
                snap.account_error = f"{type(exc).__name__}: {exc}"
                log.warning("account_sync.account_failed", error=snap.account_error)
        return snap


def _dedupe(fills: Iterable[IBFill]) -> list[IBFill]:
    seen: dict[str, IBFill] = {}
    for f in fills:
        seen[f.execution.execId] = f
    return list(seen.values())
