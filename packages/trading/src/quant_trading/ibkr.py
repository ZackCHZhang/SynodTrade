"""IBKR broker via `ib_async`: places, tracks and cancels real (paper or live) orders.

Safety, in addition to the pipeline's live guard:
- LIVE requires QUANT_ALLOW_LIVE=1 (checked at construction and on connect);
- after connecting, the accounts the gateway manages are checked against the mode: PAPER
  refuses any non-paper account (IBKR paper account ids start with "D"), LIVE refuses paper
  accounts, and the configured account must be one of them;
- every order carries the account id and our client_order_id (as `orderRef`), so it can be
  found again after a restart instead of being sent twice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

from ib_async import IB, Contract, LimitOrder, MarketOrder, Order, Stock, Trade
from ib_async import Fill as IBFill

from quant_core.config import AccountConfig
from quant_core.logging import get_logger
from quant_core.models import (
    Fill,
    Instrument,
    OrderIntent,
    OrderResult,
    OrderStatus,
    OrderType,
    RunMode,
)
from quant_core.safety import ensure_mode_allowed
from quant_core.timeutil import utcnow
from quant_trading.broker import BrokerError

log = get_logger(__name__)

# Trading uses its own connection: account client_id + 1 (market data: +0, news: +2).
CLIENT_ID_OFFSET = 1

_STATUS = {
    "PendingSubmit": OrderStatus.PENDING_SUBMIT,
    "ApiPending": OrderStatus.PENDING_SUBMIT,
    "PreSubmitted": OrderStatus.SUBMITTED,
    "Submitted": OrderStatus.SUBMITTED,
    "ApiUpdate": OrderStatus.SUBMITTED,
    "Filled": OrderStatus.FILLED,
    "Cancelled": OrderStatus.CANCELLED,
    "ApiCancelled": OrderStatus.CANCELLED,
    "Inactive": OrderStatus.REJECTED,
    "ValidationError": OrderStatus.REJECTED,
}


def is_paper_account(account_id: str) -> bool:
    return account_id.upper().startswith("D")


def to_status(ib_status: str, filled: Decimal) -> OrderStatus:
    status = _STATUS.get(ib_status, OrderStatus.SUBMITTED)
    if status is OrderStatus.SUBMITTED and filled > 0:
        return OrderStatus.PARTIALLY_FILLED
    return status


def convert_fills(intent: OrderIntent, fills: list[IBFill], *, final: bool) -> list[Fill]:
    """Fills whose commission report has arrived (all of them once the order is final;
    fills are stored once, so waiting avoids recording a commission of 0)."""
    out = []
    for f in fills:
        report = f.commissionReport
        has_report = bool(report and report.execId == f.execution.execId)
        if not (has_report or final):
            continue
        out.append(
            Fill(
                exec_id=f.execution.execId,
                client_order_id=intent.client_order_id,
                symbol=intent.symbol,
                side=intent.side,
                qty=Decimal(str(f.execution.shares)),
                price=Decimal(str(f.execution.price)),
                commission=Decimal(str(report.commission)) if has_report else Decimal(0),
                ts=f.time or utcnow(),
            )
        )
    return out


def result_from_trade(intent: OrderIntent, trade: Trade) -> OrderResult:
    st = trade.orderStatus
    filled = Decimal(str(st.filled or 0))
    status = to_status(st.status, filled)
    return OrderResult(
        client_order_id=intent.client_order_id,
        status=status,
        broker_order_id=str(trade.order.permId or trade.order.orderId) or None,
        filled_qty=filled,
        avg_fill_price=Decimal(str(st.avgFillPrice)) if filled > 0 else None,
        fills=convert_fills(intent, list(trade.fills), final=status.is_terminal),
        message="; ".join(e.message for e in trade.log if e.message)[-500:] or None,
    )


class IBKRBroker:
    name = "ibkr"
    mode: RunMode

    def __init__(
        self,
        *,
        mode: RunMode,
        account_id: str,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 18,
        connect_timeout_s: float = 10.0,
        cancel_wait_s: float = 10.0,
        not_transmitted_warn_s: float = 30.0,
        env: dict[str, str] | None = None,
        ib: IB | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if mode is RunMode.DRY_RUN:
            raise BrokerError("IBKRBroker is for paper or live mode; use DryRunBroker for dry runs")
        self.mode = mode
        self._env = env
        ensure_mode_allowed(mode, env)
        self.account_id = account_id
        self.host, self.port, self.client_id = host, port, client_id
        self.connect_timeout_s = connect_timeout_s
        self.cancel_wait_s = cancel_wait_s
        self.not_transmitted_warn_s = not_transmitted_warn_s
        self._ib = ib or IB()
        self._sleep = sleep
        self._refs: set[str] = set()  # client order ids handled by this broker
        self._warned: set[str] = set()
        self._subscribed = False

    @classmethod
    def from_account(cls, account: AccountConfig, mode: RunMode, **kwargs: Any) -> IBKRBroker:
        return cls(
            mode=mode,
            account_id=account.account_id,
            host=account.host,
            port=account.port,
            client_id=account.client_id + CLIENT_ID_OFFSET,
            **kwargs,
        )

    # ------------------------------------------------------------ connection

    async def connect(self) -> None:
        if self._ib.isConnected():
            return
        ensure_mode_allowed(self.mode, self._env)
        await self._ib.connectAsync(
            self.host, self.port, clientId=self.client_id, timeout=self.connect_timeout_s
        )
        try:
            self._check_accounts(self._ib.managedAccounts())
        except BrokerError:
            self._ib.disconnect()
            raise
        self._subscribe()
        log.info("ibkr_broker.connected", mode=self.mode.value, account=self.account_id)

    def _subscribe(self) -> None:
        """Log status changes and IBKR errors of our orders (diagnostics only)."""
        if self._subscribed:
            return
        status_event = getattr(self._ib, "orderStatusEvent", None)
        error_event = getattr(self._ib, "errorEvent", None)
        if status_event is not None:
            status_event += self._on_status
        if error_event is not None:
            error_event += self._on_error
        self._subscribed = True

    def _on_status(self, trade: Trade) -> None:
        if trade.order.orderRef not in self._refs:
            return
        st = trade.orderStatus
        log.info(
            "ibkr_broker.order_status",
            client_order_id=trade.order.orderRef,
            status=st.status,
            filled=st.filled,
            why_held=st.whyHeld or None,
            perm_id=trade.order.permId or None,
        )

    def _on_error(self, req_id: int, code: int, message: str, contract: Any = None) -> None:
        trade = next((t for t in self._ib.trades() if t.order.orderId == req_id), None)
        if trade is None or trade.order.orderRef not in self._refs:
            return
        log.warning(
            "ibkr_broker.order_error",
            client_order_id=trade.order.orderRef,
            code=code,
            message=message,
        )

    def _check_transmitted(self, trade: Trade) -> None:
        """TWS gives an order a permanent id once IBKR's servers accepted it. Without one
        after a while, TWS is holding it locally, typically behind a confirmation dialog."""
        ref = trade.order.orderRef
        if trade.order.permId or trade.isDone() or ref in self._warned or not trade.log:
            return
        if (utcnow() - trade.log[0].time).total_seconds() < self.not_transmitted_warn_s:
            return
        self._warned.add(ref)
        log.warning(
            "ibkr_broker.not_transmitted",
            client_order_id=ref,
            status=trade.orderStatus.status,
            hint="TWS has not sent this order to IBKR: look for an order confirmation dialog "
            "in TWS, or enable Global Configuration > API > Precautions > "
            "'Bypass Order Precautions for API Orders'",
        )

    def _check_accounts(self, managed: list[str]) -> None:
        if self.account_id not in managed:
            raise BrokerError(f"account {self.account_id} is not managed by this gateway")
        if self.mode is RunMode.PAPER and not all(is_paper_account(a) for a in managed):
            raise BrokerError("mode is paper but the gateway is logged into a live account")
        if self.mode is RunMode.LIVE and is_paper_account(self.account_id):
            raise BrokerError("mode is live but the account is a paper account")

    async def disconnect(self) -> None:
        if self._ib.isConnected():
            self._ib.disconnect()

    async def is_healthy(self) -> bool:
        if not self._ib.isConnected():
            return False
        try:
            await self._ib.reqCurrentTimeAsync()
        except Exception:
            return False
        return True

    def _require_connection(self) -> None:
        if not self._ib.isConnected():
            raise BrokerError(f"not connected to IBKR at {self.host}:{self.port}")

    # ------------------------------------------------------------ orders

    async def _contract(self, instrument: Instrument) -> Contract:
        if instrument.con_id is not None:
            return Contract(conId=instrument.con_id, exchange=instrument.exchange)
        [contract] = await self._ib.qualifyContractsAsync(
            Stock(instrument.symbol, "SMART", instrument.currency)
        )
        if not isinstance(contract, Contract) or not contract.conId:
            raise BrokerError(f"IBKR does not know the stock {instrument.symbol}")
        return contract

    def _find(self, client_order_id: str) -> Trade | None:
        matches = [t for t in self._ib.trades() if t.order.orderRef == client_order_id]
        return matches[-1] if matches else None

    async def submit(self, intent: OrderIntent, instrument: Instrument) -> OrderResult:
        self._require_connection()
        ensure_mode_allowed(self.mode, self._env)
        action = "BUY" if intent.side.value == "buy" else "SELL"
        common: dict[str, Any] = {
            "orderRef": intent.client_order_id,
            "account": self.account_id,
            "tif": intent.time_in_force,
        }
        qty = float(intent.quantity)
        order: Order
        if intent.order_type is OrderType.LIMIT:
            assert intent.limit_price is not None
            order = LimitOrder(action, qty, float(intent.limit_price), **common)
        else:
            order = MarketOrder(action, qty, **common)
        self._refs.add(intent.client_order_id)
        trade = self._ib.placeOrder(await self._contract(instrument), order)
        log.info(
            "ibkr_broker.submitted",
            client_order_id=intent.client_order_id,
            symbol=intent.symbol,
            side=action,
            qty=str(intent.quantity),
            limit=str(intent.limit_price),
        )
        return result_from_trade(intent, trade)

    async def lookup(self, intent: OrderIntent) -> OrderResult | None:
        self._require_connection()
        trade = self._find(intent.client_order_id)
        if trade is None:
            await self._ib.reqAllOpenOrdersAsync()  # orders placed by earlier sessions
            trade = self._find(intent.client_order_id)
        if trade is not None:
            self._check_transmitted(trade)
            return result_from_trade(intent, trade)
        fills = [
            f
            for f in await self._ib.reqExecutionsAsync()
            if f.execution.orderRef == intent.client_order_id
        ]
        if not fills:
            return None
        filled = sum((Decimal(str(f.execution.shares)) for f in fills), Decimal(0))
        return OrderResult(
            client_order_id=intent.client_order_id,
            status=OrderStatus.FILLED
            if filled >= intent.quantity
            else OrderStatus.PARTIALLY_FILLED,
            filled_qty=filled,
            avg_fill_price=Decimal(str(fills[-1].execution.avgPrice)),
            fills=convert_fills(intent, fills, final=True),
            message="recovered from executions",
        )

    async def cancel(self, intent: OrderIntent) -> OrderResult:
        self._require_connection()
        trade = self._find(intent.client_order_id)
        if trade is None:
            raise BrokerError(f"no open IBKR order for {intent.client_order_id}")
        if not trade.isDone():
            self._ib.cancelOrder(trade.order)
            # wait for IBKR to confirm, so the caller records the real final status
            waited = 0.0
            while not trade.isDone() and waited < self.cancel_wait_s:
                await self._sleep(0.25)
                waited += 0.25
            if not trade.isDone():
                log.warning(
                    "ibkr_broker.cancel_unconfirmed",
                    client_order_id=intent.client_order_id,
                    status=trade.orderStatus.status,
                    perm_id=trade.order.permId or None,
                )
        return result_from_trade(intent, trade)
