"""
Tests for Portfolio Rebalancing System
=======================================
Run with: python test_portfolio.py
Or with pytest: pytest test_portfolio.py -v
"""

import unittest
from decimal import Decimal

from portfolio import (
    Stock,
    Holding,
    Portfolio,
    Trade,
    TradeAction,
    RebalanceResult,
    to_decimal,
)


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------


class TestStock(unittest.TestCase):

    def test_stock_creation(self):
        stock = Stock(ticker="AAPL", current_price=228)
        self.assertEqual(stock.ticker, "AAPL")
        self.assertEqual(stock.current_price, Decimal("228"))

    def test_negative_price_raises(self):
        with self.assertRaises(ValueError):
            Stock(ticker="BAD", current_price=-10)

    def test_empty_ticker_raises(self):
        with self.assertRaises(ValueError):
            Stock(ticker="", current_price=100)

    def test_whitespace_ticker_raises(self):
        with self.assertRaises(ValueError):
            Stock(ticker="   ", current_price=100)

    def test_ticker_normalized_to_uppercase(self):
        stock = Stock(ticker="aapl", current_price=100)
        self.assertEqual(stock.ticker, "AAPL")

    def test_ticker_stripped(self):
        stock = Stock(ticker="  meta  ", current_price=100)
        self.assertEqual(stock.ticker, "META")

    def test_zero_price_allowed(self):
        stock = Stock(ticker="DELIST", current_price=0)
        self.assertEqual(stock.current_price, Decimal("0"))

    def test_price_stored_as_decimal(self):
        stock = Stock(ticker="X", current_price=99.99)
        self.assertIsInstance(stock.current_price, Decimal)


# ---------------------------------------------------------------------------
# Holding
# ---------------------------------------------------------------------------


class TestHolding(unittest.TestCase):

    def test_market_value(self):
        stock = Stock("META", current_price=500)
        holding = Holding(stock=stock, shares=10)
        self.assertEqual(holding.market_value, Decimal("5000"))

    def test_fractional_shares(self):
        stock = Stock("AAPL", current_price=200)
        holding = Holding(stock=stock, shares=0.5)
        self.assertEqual(holding.market_value, Decimal("100"))

    def test_negative_shares_raises(self):
        stock = Stock("BAD", current_price=100)
        with self.assertRaises(ValueError):
            Holding(stock=stock, shares=-5)

    def test_zero_shares_allowed(self):
        stock = Stock("ZERO", current_price=100)
        holding = Holding(stock=stock, shares=0)
        self.assertEqual(holding.market_value, Decimal("0"))

    def test_shares_stored_as_decimal(self):
        stock = Stock("X", current_price=100)
        holding = Holding(stock=stock, shares=10)
        self.assertIsInstance(holding.shares, Decimal)


# ---------------------------------------------------------------------------
# Portfolio Allocation
# ---------------------------------------------------------------------------


class TestPortfolioAllocation(unittest.TestCase):

    def test_valid_allocation(self):
        portfolio = Portfolio(allocation={"META": 0.4, "AAPL": 0.6})
        self.assertEqual(portfolio.allocation["META"], Decimal("0.4"))

    def test_allocation_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            Portfolio(allocation={"META": 0.5, "AAPL": 0.3})

    def test_negative_weight_raises(self):
        with self.assertRaises(ValueError):
            Portfolio(allocation={"META": -0.2, "AAPL": 1.2})

    def test_weight_over_one_raises(self):
        with self.assertRaises(ValueError):
            Portfolio(allocation={"META": 1.5, "AAPL": -0.5})

    def test_allocation_keys_normalized_to_uppercase(self):
        portfolio = Portfolio(allocation={"meta": 0.4, "aapl": 0.6})
        self.assertIn("META", portfolio.allocation)
        self.assertIn("AAPL", portfolio.allocation)

    def test_allocation_duplicate_tickers_case_insensitive(self):
        with self.assertRaises(ValueError):
            Portfolio(allocation={"META": 0.4, "meta": 0.6})


# ---------------------------------------------------------------------------
# Portfolio Duplicates
# ---------------------------------------------------------------------------


class TestPortfolioDuplicates(unittest.TestCase):

    def test_duplicate_tickers_in_holdings_raises(self):
        a = Stock("AAPL", current_price=100)
        with self.assertRaises(ValueError):
            Portfolio(holdings=[Holding(a, shares=10), Holding(a, shares=5)])

    def test_case_insensitive_duplicate_caught(self):
        """Stock.__post_init__ normalizes to uppercase, so this is caught."""
        a1 = Stock("aapl", current_price=100)
        a2 = Stock("AAPL", current_price=100)
        with self.assertRaises(ValueError):
            Portfolio(holdings=[Holding(a1, shares=10), Holding(a2, shares=5)])

    def test_add_holding_rejects_duplicate(self):
        a = Stock("AAPL", current_price=100)
        p = Portfolio(holdings=[Holding(a, shares=10)])
        with self.assertRaises(ValueError):
            p.add_holding(Holding(Stock("AAPL", current_price=110), shares=5))


# ---------------------------------------------------------------------------
# Rebalance Core
# ---------------------------------------------------------------------------


class TestRebalance(unittest.TestCase):

    def _make_portfolio(self):
        meta = Stock("META", current_price=500)
        aapl = Stock("AAPL", current_price=200)
        return Portfolio(
            holdings=[
                Holding(stock=meta, shares=10),   # $5,000
                Holding(stock=aapl, shares=50),    # $10,000
            ],
            allocation={"META": 0.50, "AAPL": 0.50},
        )

    def test_rebalance_generates_trades(self):
        """META=$5k (33%), AAPL=$10k (67%). Target 50/50 -> BUY META, SELL AAPL."""
        portfolio = self._make_portfolio()
        result = portfolio.rebalance(threshold=0.0)
        self.assertEqual(len(result.trades), 2)

        sell_trade = next(t for t in result.trades if t.action == TradeAction.SELL)
        buy_trade = next(t for t in result.trades if t.action == TradeAction.BUY)
        self.assertEqual(sell_trade.ticker, "AAPL")
        self.assertEqual(buy_trade.ticker, "META")

    def test_sells_come_before_buys(self):
        """SELLs first to free up cash."""
        portfolio = self._make_portfolio()
        result = portfolio.rebalance(threshold=0.0)
        actions = [t.action for t in result.trades]
        self.assertEqual(actions, [TradeAction.SELL, TradeAction.BUY])

    def test_balanced_portfolio_no_trades(self):
        stock_a = Stock("A", current_price=100)
        stock_b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=stock_a, shares=50),
                Holding(stock=stock_b, shares=50),
            ],
            allocation={"A": 0.50, "B": 0.50},
        )
        result = portfolio.rebalance(threshold=0.01)
        self.assertEqual(result.trades, [])
        self.assertTrue(result.is_balanced)

    def test_threshold_filters_small_drifts(self):
        stock_a = Stock("A", current_price=100)
        stock_b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=stock_a, shares=48),
                Holding(stock=stock_b, shares=52),
            ],
            allocation={"A": 0.50, "B": 0.50},
        )
        # 2% drift < 5% threshold -> no trades
        result = portfolio.rebalance(threshold=0.05)
        self.assertEqual(result.trades, [])
        # 2% drift > 1% threshold -> trades
        result = portfolio.rebalance(threshold=0.01)
        self.assertEqual(len(result.trades), 2)

    def test_three_stock_rebalance(self):
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        c = Stock("C", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=60),
                Holding(stock=b, shares=30),
                Holding(stock=c, shares=10),
            ],
            allocation={"A": 0.34, "B": 0.33, "C": 0.33},
        )
        result = portfolio.rebalance(threshold=0.01)
        sell_trades = [t for t in result.trades if t.action == TradeAction.SELL]
        buy_trades = [t for t in result.trades if t.action == TradeAction.BUY]
        self.assertGreaterEqual(len(sell_trades), 1)
        self.assertEqual(sell_trades[0].ticker, "A")
        self.assertTrue(any(t.ticker == "C" for t in buy_trades))


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases(unittest.TestCase):

    def test_no_allocation_raises(self):
        stock = Stock("A", current_price=100)
        portfolio = Portfolio(holdings=[Holding(stock=stock, shares=10)])
        with self.assertRaises(ValueError):
            portfolio.rebalance()

    def test_no_holdings_raises(self):
        portfolio = Portfolio(allocation={"A": 1.0})
        with self.assertRaises(ValueError):
            portfolio.rebalance()

    def test_zero_value_portfolio_raises(self):
        stock = Stock("A", current_price=0)
        portfolio = Portfolio(
            holdings=[Holding(stock=stock, shares=10)],
            allocation={"A": 1.0},
        )
        with self.assertRaises(ValueError):
            portfolio.rebalance()

    def test_total_value(self):
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=200)
        portfolio = Portfolio(
            holdings=[Holding(stock=a, shares=10), Holding(stock=b, shares=5)]
        )
        self.assertEqual(portfolio.total_value, Decimal("2000"))

    def test_current_weights(self):
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[Holding(stock=a, shares=75), Holding(stock=b, shares=25)]
        )
        weights = portfolio.current_weights
        self.assertEqual(weights["A"], Decimal("75") / Decimal("100"))
        self.assertEqual(weights["B"], Decimal("25") / Decimal("100"))


# ---------------------------------------------------------------------------
# Allocation-Holdings Mismatch
# ---------------------------------------------------------------------------


class TestAllocationHoldingsMismatch(unittest.TestCase):

    def test_holding_not_in_allocation_triggers_sell_all(self):
        """If we hold a stock not in the target allocation, liquidate it."""
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=50),
                Holding(stock=b, shares=50),
            ],
            allocation={"A": 1.0},  # B not in allocation
        )
        result = portfolio.rebalance(threshold=0.0)
        sell_b = [t for t in result.trades if t.ticker == "B" and t.action == TradeAction.SELL]
        self.assertEqual(len(sell_b), 1)
        self.assertEqual(sell_b[0].shares, Decimal("50"))

    def test_allocation_not_in_holdings_warns(self):
        """If allocation references a stock we don't hold, emit a warning."""
        a = Stock("A", current_price=100)
        portfolio = Portfolio(
            holdings=[Holding(stock=a, shares=100)],
            allocation={"A": 0.6, "B": 0.4},
        )
        result = portfolio.rebalance(threshold=0.0)
        self.assertTrue(any("B" in w for w in result.warnings))

    def test_zero_share_holding_enables_buy(self):
        """Adding a zero-share holding provides price info, enabling a BUY trade."""
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=200)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=100),  # $10,000
                Holding(stock=b, shares=0),     # $0 but has price info
            ],
            allocation={"A": 0.5, "B": 0.5},
        )
        result = portfolio.rebalance(threshold=0.0)
        buy_b = [t for t in result.trades if t.ticker == "B" and t.action == TradeAction.BUY]
        self.assertEqual(len(buy_b), 1)
        self.assertGreater(buy_b[0].shares, Decimal("0"))
        self.assertEqual(result.warnings, [])  # no warning because B is in holdings


# ---------------------------------------------------------------------------
# RebalanceResult
# ---------------------------------------------------------------------------


class TestRebalanceResult(unittest.TestCase):

    def test_is_balanced_when_no_trades(self):
        result = RebalanceResult()
        self.assertTrue(result.is_balanced)

    def test_net_cash_flow_near_zero_for_balanced_rebalance(self):
        """A proper rebalance should have sells ≈ buys (net cash ≈ 0)."""
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=70),
                Holding(stock=b, shares=30),
            ],
            allocation={"A": 0.5, "B": 0.5},
        )
        result = portfolio.rebalance(threshold=0.0)
        # Net cash should be close to zero (sells fund the buys)
        self.assertTrue(abs(result.net_cash_flow) < Decimal("1"))

    def test_total_sell_value(self):
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=80),  # $8,000
                Holding(stock=b, shares=20),  # $2,000
            ],
            allocation={"A": 0.5, "B": 0.5},
        )
        result = portfolio.rebalance(threshold=0.0)
        # Should sell $3,000 of A and buy $3,000 of B
        self.assertEqual(result.total_sell_value, Decimal("3000"))
        self.assertEqual(result.total_buy_value, Decimal("3000"))


# ---------------------------------------------------------------------------
# Cash Position
# ---------------------------------------------------------------------------


class TestCashPosition(unittest.TestCase):

    def test_cash_included_in_total_value(self):
        a = Stock("A", current_price=100)
        portfolio = Portfolio(
            holdings=[Holding(stock=a, shares=10)],
            cash=500,
        )
        self.assertEqual(portfolio.total_value, Decimal("1500"))

    def test_negative_cash_raises(self):
        with self.assertRaises(ValueError):
            Portfolio(cash=-100)

    def test_rebalance_deploys_cash(self):
        """Idle cash gets deployed toward target allocation."""
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=50),  # $5,000
                Holding(stock=b, shares=50),  # $5,000
            ],
            allocation={"A": 0.5, "B": 0.5},
            cash=2000,  # $2,000 idle
        )
        # Total = $12,000. Each should be $6,000. Currently $5,000 each.
        # Both need BUY $1,000.
        result = portfolio.rebalance(threshold=0.0)
        buy_trades = [t for t in result.trades if t.action == TradeAction.BUY]
        self.assertEqual(len(buy_trades), 2)
        total_buys = sum(t.estimated_value for t in buy_trades)
        self.assertEqual(total_buys, Decimal("2000"))


# ---------------------------------------------------------------------------
# Decimal Precision
# ---------------------------------------------------------------------------


class TestDecimalPrecision(unittest.TestCase):

    def test_thirds_allocation_no_float_drift(self):
        """1/3 + 1/3 + 1/3 should be handled without floating point drift."""
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        c = Stock("C", current_price=100)
        # Use Decimal strings for exact thirds
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=100),
                Holding(stock=b, shares=100),
                Holding(stock=c, shares=100),
            ],
            allocation={
                "A": Decimal("0.334"),
                "B": Decimal("0.333"),
                "C": Decimal("0.333"),
            },
        )
        result = portfolio.rebalance(threshold=0.0)
        # Portfolio is nearly balanced; only tiny drift from .334 vs .333
        for trade in result.trades:
            self.assertLess(trade.estimated_value, Decimal("200"))

    def test_to_decimal_avoids_float_inheritance(self):
        """to_decimal(0.1) should give exactly 0.1, not 0.10000000000000000555..."""
        d = to_decimal(0.1)
        self.assertEqual(d, Decimal("0.1"))


# ---------------------------------------------------------------------------
# TradeAction Enum
# ---------------------------------------------------------------------------


class TestTradeAction(unittest.TestCase):

    def test_enum_values(self):
        self.assertEqual(TradeAction.BUY.value, "BUY")
        self.assertEqual(TradeAction.SELL.value, "SELL")

    def test_string_comparison(self):
        """TradeAction inherits from str, so direct comparison works."""
        self.assertEqual(TradeAction.BUY, "BUY")
        self.assertEqual(TradeAction.SELL, "SELL")

    def test_invalid_action_not_in_enum(self):
        with self.assertRaises(ValueError):
            TradeAction("HOLD")


# ---------------------------------------------------------------------------
# Rebalance Idempotency
# ---------------------------------------------------------------------------


class TestRebalanceIdempotent(unittest.TestCase):

    def test_rebalance_twice_produces_same_result(self):
        """rebalance() is a pure computation — calling it twice gives the same output."""
        a = Stock("A", current_price=100)
        b = Stock("B", current_price=100)
        portfolio = Portfolio(
            holdings=[
                Holding(stock=a, shares=70),
                Holding(stock=b, shares=30),
            ],
            allocation={"A": 0.5, "B": 0.5},
        )
        result1 = portfolio.rebalance(threshold=0.0)
        result2 = portfolio.rebalance(threshold=0.0)
        self.assertEqual(len(result1.trades), len(result2.trades))
        for t1, t2 in zip(result1.trades, result2.trades):
            self.assertEqual(t1.ticker, t2.ticker)
            self.assertEqual(t1.action, t2.action)
            self.assertEqual(t1.shares, t2.shares)
            self.assertEqual(t1.estimated_value, t2.estimated_value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
