"""Equity fraccionario (fork equity-fractional, ADR-004): gates de aceptación.

Defaults enteros intactos; con size_precision=9 la cantidad, el risk, el matching, la
posición y la persistencia se comportan con 9 decimales exactos.
"""

from __future__ import annotations

import random
from decimal import Decimal

from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import Equity
from nautilus_trader.model.objects import Currency, Price, Quantity

VENUE = "XNAS"


def equity_instrument(symbol, venue, size_precision=9, increment="0.000000001"):
    return Equity(
        instrument_id=InstrumentId.from_str(f"{symbol}.{venue}"), raw_symbol=Symbol(symbol), currency=Currency.from_str("USD"),
        price_precision=2, price_increment=Price.from_str("0.01"), lot_size=Quantity.from_int(100), ts_event=0, ts_init=0,
        size_precision=size_precision, size_increment=Quantity.from_str(increment),
    )


def _fill(instrument, side, qty, i, px="100.00"):
    from nautilus_trader.core.uuid import UUID4
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.enums import LiquiditySide, OrderType
    from nautilus_trader.model.events import OrderFilled
    from nautilus_trader.model.identifiers import (
        AccountId,
        ClientOrderId,
        PositionId,
        StrategyId,
        TradeId,
        TraderId,
        VenueOrderId,
    )
    from nautilus_trader.model.objects import Money, Price, Quantity

    return OrderFilled(
        trader_id=TraderId("T-001"), strategy_id=StrategyId("S-001"), instrument_id=instrument.id,
        client_order_id=ClientOrderId(f"O-{i}"), venue_order_id=VenueOrderId(f"V-{i}"), account_id=AccountId("A-001"),
        trade_id=TradeId(f"t{i}"), position_id=PositionId("P-1"), order_side=side, order_type=OrderType.MARKET,
        last_qty=Quantity.from_str(str(qty)), last_px=Price.from_str(px), currency=USD, commission=Money(0, USD),
        liquidity_side=LiquiditySide.TAKER, event_id=UUID4(), ts_event=i, ts_init=i,
    )


def _position(instrument, side, qty):
    from nautilus_trader.model.position import Position

    return Position(instrument=instrument, fill=_fill(instrument, side, qty, 1))


def test_equity_9_decimales_y_roundtrip_dict():
    inst = equity_instrument("SOFI", VENUE)
    assert (inst.size_precision, str(inst.size_increment)) == (9, "0.000000001")
    again = Equity.from_dict(Equity.to_dict(inst))
    assert again == inst and again.size_precision == 9


def test_make_qty_exacto_a_9_decimales():
    inst = equity_instrument("SOFI", VENUE)
    assert str(inst.make_qty("0.123456789")) == "0.123456789"
    assert str(inst.make_qty(Decimal("8388607.123456789"))) == "8388607.123456789"
    assert inst.make_qty(0.5).as_decimal() == Decimal("0.5")


def test_make_qty_devuelve_la_precision_del_instrumento():
    inst = equity_instrument("SOFI", VENUE)
    assert inst.make_qty(0.5).precision == inst.size_precision == 9


def test_defaults_enteros_intactos():
    inst = Equity(
        instrument_id=InstrumentId.from_str("AAPL.XNAS"), raw_symbol=Symbol("AAPL"), currency=Currency.from_str("USD"),
        price_precision=2, price_increment=Price.from_str("0.01"), lot_size=Quantity.from_int(100), ts_event=0, ts_init=0,
    )
    assert (inst.size_precision, str(inst.size_increment)) == (0, "1")


def test_position_exacta_en_casos_limite():
    from nautilus_trader.model.enums import OrderSide

    inst = equity_instrument("SOFI", VENUE)
    for qty in ("0.000000001", "0.123456789", "1000000.000000001"):
        pos = _position(inst, OrderSide.BUY, qty)
        assert pos.quantity.as_decimal() == Decimal(qty)
    pos = _position(inst, OrderSide.BUY, "0.1")
    for i in range(2, 11):
        pos.apply(_fill(inst, OrderSide.BUY, "0.1", i))
    assert str(pos.quantity) == "1.000000000"


def test_1000_fills_contra_oraculo_decimal_y_cierre_en_cero():
    from nautilus_trader.model.enums import OrderSide

    rng = random.Random(43)
    inst = equity_instrument("SOFI", VENUE)
    first = Decimal(rng.randrange(1, 10**9)) / Decimal(10**9)
    pos = _position(inst, OrderSide.BUY, first)
    oracle = first
    for i in range(2, 1001):
        q = Decimal(rng.randrange(1, 10**9)) / Decimal(10**9)
        pos.apply(_fill(inst, OrderSide.BUY, q, i))
        oracle += q
        assert pos.quantity.as_decimal() == oracle, f"fill {i}"
    pos.apply(_fill(inst, OrderSide.SELL, oracle, 1001))
    assert pos.is_closed and pos.quantity.raw == 0


def _engine_with_strategy(qty="0.123456789", increment="0.000000001", prec=9):
    import pandas as pd
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.config import LoggingConfig, StrategyConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
    from nautilus_trader.model.identifiers import TraderId, Venue
    from nautilus_trader.model.objects import Money
    from nautilus_trader.trading.strategy import Strategy

    inst = equity_instrument("SOFI", VENUE, prec, increment)
    iid = inst.id
    bar_type = BarType.from_str(f"{iid}-1-DAY-LAST-EXTERNAL")

    class _Cfg(StrategyConfig, frozen=True):
        pass

    class _S(Strategy):
        def __init__(self):
            super().__init__(_Cfg())
            self.events = []
            self._n = 0

        def on_start(self):
            self.subscribe_bars(bar_type)

        def on_bar(self, bar):
            self._n += 1
            if self._n == 1:
                self.submit_order(self.order_factory.market(
                    iid, OrderSide.BUY, Quantity.from_str(qty), time_in_force=TimeInForce.DAY))

        def on_event(self, event):
            self.events.append(event)

    engine = BacktestEngine(config=BacktestEngineConfig(trader_id=TraderId("BT-001"), logging=LoggingConfig(log_level="ERROR")))
    engine.add_venue(venue=Venue(VENUE), oms_type=OmsType.HEDGING, account_type=AccountType.MARGIN, base_currency=USD,
                     starting_balances=[Money(100_000, USD)])
    engine.add_instrument(inst)
    days = pd.date_range("2026-01-05", periods=3, tz="UTC")
    engine.add_data([
        Bar(bar_type, Price.from_str("100.00"), Price.from_str("101.00"), Price.from_str("99.00"), Price.from_str("100.00"),
            Quantity.from_int(1_000_000), int(d.value), int(d.value))
        for d in days
    ])
    strat = _S()
    engine.add_strategy(strat)
    engine.run()
    return strat, engine


def _names(strat):
    return [type(e).__name__ for e in strat.events]


def test_end_to_end_orden_fill_posicion_exacta():
    strat, engine = _engine_with_strategy(qty="0.123456789")
    try:
        names = _names(strat)
        assert "OrderFilled" in names and "OrderDenied" not in names, names
        fill = next(e for e in strat.events if type(e).__name__ == "OrderFilled")
        assert str(fill.last_qty) == "0.123456789"
        opened = next(e for e in strat.events if type(e).__name__ == "PositionOpened")
        assert str(opened.quantity) == "0.123456789"
    finally:
        engine.dispose()


def test_risk_deniega_fraccion_con_incremento_entero():
    strat, engine = _engine_with_strategy(qty="0.5", increment="1.000000000", prec=9)
    try:
        names = _names(strat)
        assert "OrderDenied" in names and "OrderFilled" not in names, names
        denied = next(e for e in strat.events if type(e).__name__ == "OrderDenied")
        assert "not aligned to size increment" in denied.reason
    finally:
        engine.dispose()


def test_risk_deniega_precision_mayor_a_la_del_instrumento():
    strat, engine = _engine_with_strategy(qty="0.1234567891", increment="0.000000001", prec=9)
    try:
        denied = [e for e in strat.events if type(e).__name__ == "OrderDenied"]
        assert denied and "precision" in denied[0].reason
    finally:
        engine.dispose()


def test_parquet_catalog_guarda_y_lee_el_equity_fraccionario(tmp_path):
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    inst = equity_instrument("SOFI", VENUE)
    catalog = ParquetDataCatalog(tmp_path)
    catalog.write_data([inst])
    back = catalog.instruments()
    assert len(back) == 1 and back[0].size_precision == 9 and str(back[0].size_increment) == "0.000000001"


def test_from_dict_tolera_catalogo_viejo_con_columnas_nulas():
    """Un catálogo escrito con la wheel oficial lee size_precision/size_increment como None -> 0 / 1."""
    d = Equity.to_dict(equity_instrument("AAPL", VENUE))
    d["size_precision"], d["size_increment"] = None, None
    back = Equity.from_dict(d)
    assert (back.size_precision, str(back.size_increment)) == (0, "1")
