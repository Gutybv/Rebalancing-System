"""
Portfolio Rebalancing System
============================
Fintual Software Engineer (Operations / Automation) - Coding Challenge

Author: Benjamín Gutiérrez Martínez
Date: February 2026

Design Decisions:
-----------------
1. I chose Python for readability and because it's the language I'm most productive in.
   Fintual uses Django and Python in their stack, so it aligns well.

2. The rebalance method returns a RebalanceResult (trades + warnings) rather than
   executing trades directly. This follows the command pattern — in a real system,
   you'd want to review trades before execution, especially in a regulated environment
   like mutual funds.

3. I used dataclasses for clean, minimal boilerplate. In production, these would
   likely be ORM models (Django models, for example).

4. The allocation is validated on assignment to catch configuration errors early,
   not at rebalance time when it's too late.

5. I added a `threshold` parameter to avoid unnecessary micro-trades. In real
   operations, every trade has costs (fees, slippage, tax events), so you only
   want to rebalance when the drift is meaningful.

6. All financial calculations use Decimal instead of float. This is not premature
   optimization — it's a correctness requirement. With floats, 0.1 + 0.2 != 0.3,
   which is unacceptable when handling real money.

7. TradeAction is an enum that inherits from str, making it safe against typos
   ("Buy", "BYU") while remaining serialization-friendly.

8. Cash is a first-class concept. Idle cash is a drag on returns in a robo-advisor,
   so the rebalancer naturally deploys it toward the target allocation.
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from enum import Enum


# ---------------------------------------------------------------------------
# Helpers & Types
# ---------------------------------------------------------------------------

Money = Decimal
Weight = Decimal

_SHARE_PRECISION = Decimal("0.0001")
_MONEY_PRECISION = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """
    Convert a numeric value to Decimal safely.

    Uses str() as intermediary to avoid Decimal's float precision inheritance.
    Decimal(0.1) gives 0.1000000000000000055511151231257827021181583404541015625
    Decimal(str(0.1)) gives 0.1
    """
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Cannot convert {value!r} to Decimal: {e}")


class TradeAction(str, Enum):
    """
    Trade direction. Inherits from str so TradeAction.BUY == "BUY" is True,
    and JSON serialization works cleanly.
    """
    BUY = "BUY"
    SELL = "SELL"


# ---------------------------------------------------------------------------
# Core Models
# ---------------------------------------------------------------------------

@dataclass
class Stock:
    """
    Represents a stock with a ticker symbol and a current price.

    In production, `current_price` would call an API (e.g., Bloomberg, Yahoo Finance)
    or query a database. Here it's a simple attribute for the exercise.
    """

    ticker: str
    current_price: Money

    def __post_init__(self):
        if not self.ticker or not self.ticker.strip():
            raise ValueError("Ticker cannot be empty")
        self.ticker = self.ticker.strip().upper()
        self.current_price = to_decimal(self.current_price)
        if self.current_price < 0:
            raise ValueError(f"Price cannot be negative for {self.ticker}")

    def __repr__(self):
        return f"Stock({self.ticker}, ${self.current_price:.2f})"


@dataclass
class Holding:
    """
    Represents a position in the portfolio: how many shares of a stock we own.

    I separated Holding from Stock because a Stock is market data (shared by everyone)
    while a Holding is portfolio-specific (how many shares *we* own).
    """

    stock: Stock
    shares: Decimal  # Decimal to support fractional shares, common in modern platforms

    def __post_init__(self):
        self.shares = to_decimal(self.shares)
        if self.shares < 0:
            raise ValueError(
                f"Shares cannot be negative for {self.stock.ticker}, got {self.shares}"
            )

    @property
    def market_value(self) -> Money:
        """Current market value of this holding."""
        return self.shares * self.stock.current_price

    def __repr__(self):
        return f"Holding({self.stock.ticker}: {self.shares} shares = ${self.market_value:.2f})"


@dataclass
class Trade:
    """
    Represents a rebalancing action: buy or sell a stock.

    This is the output of the rebalance method. In a real system, these would be
    queued for review/approval before execution — especially important in a
    regulated fund like Fintual's mutual funds.
    """

    ticker: str
    action: TradeAction
    shares: Decimal
    estimated_value: Money

    def __post_init__(self):
        self.shares = to_decimal(self.shares).quantize(_SHARE_PRECISION, ROUND_HALF_UP)
        self.estimated_value = to_decimal(self.estimated_value).quantize(
            _MONEY_PRECISION, ROUND_HALF_UP
        )

    def __repr__(self):
        return (
            f"{self.action.value} {self.shares} shares of {self.ticker} "
            f"(~${self.estimated_value})"
        )


@dataclass
class RebalanceResult:
    """
    Structured output from a rebalance operation.

    Why not just return a list of trades? In operations, you want metadata alongside
    the actions: warnings about edge cases, summary statistics for dashboards, and
    a quick check for whether the portfolio is already balanced. A structured result
    enables all of this without losing the simplicity of iterating over trades.
    """

    trades: list[Trade] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_buy_value(self) -> Money:
        return sum(
            (t.estimated_value for t in self.trades if t.action == TradeAction.BUY),
            Decimal("0"),
        )

    @property
    def total_sell_value(self) -> Money:
        return sum(
            (t.estimated_value for t in self.trades if t.action == TradeAction.SELL),
            Decimal("0"),
        )

    @property
    def net_cash_flow(self) -> Money:
        """Positive = cash surplus (more sells), negative = cash needed (more buys)."""
        return self.total_sell_value - self.total_buy_value

    @property
    def is_balanced(self) -> bool:
        return len(self.trades) == 0

    def __repr__(self):
        if self.is_balanced:
            return "RebalanceResult(balanced, no trades needed)"
        return (
            f"RebalanceResult({len(self.trades)} trades, "
            f"buy=${self.total_buy_value}, sell=${self.total_sell_value}, "
            f"net={self.net_cash_flow})"
        )


@dataclass
class Portfolio:
    """
    A portfolio with holdings, a target allocation, and optional cash.

    The allocation represents the desired distribution of the portfolio's total value.
    For example: {"META": 0.40, "AAPL": 0.60} means 40% META, 60% AAPL.

    The rebalance method computes the trades needed to move from the current
    distribution to the target allocation.
    """

    holdings: list[Holding] = field(default_factory=list)
    allocation: dict[str, Weight] = field(default_factory=dict)
    cash: Money = Decimal("0")

    def __post_init__(self):
        self.cash = to_decimal(self.cash)
        if self.cash < 0:
            raise ValueError(f"Cash cannot be negative, got {self.cash}")
        self._check_duplicate_tickers()
        if self.allocation:
            self.allocation = self._normalize_allocation(self.allocation)
            self._validate_allocation()

    def _normalize_allocation(self, allocation: dict) -> dict[str, Weight]:
        """Normalize allocation keys to uppercase and values to Decimal."""
        normalized: dict[str, Weight] = {}
        for ticker, weight in allocation.items():
            key = ticker.strip().upper()
            if key in normalized:
                raise ValueError(f"Duplicate ticker in allocation: {key}")
            normalized[key] = to_decimal(weight)
        return normalized

    def _check_duplicate_tickers(self):
        """Detect duplicate tickers in holdings (case-insensitive)."""
        seen: set[str] = set()
        for h in self.holdings:
            ticker = h.stock.ticker  # already uppercased by Stock.__post_init__
            if ticker in seen:
                raise ValueError(f"Duplicate holding for ticker: {ticker}")
            seen.add(ticker)

    def _validate_allocation(self):
        """
        Ensures the allocation percentages sum to 1.0 (100%) and all values are valid.

        Why validate early? In operations, a misconfigured allocation discovered at
        rebalance time (maybe during market hours) is much worse than catching it
        at configuration time.
        """
        for ticker, weight in self.allocation.items():
            if weight < 0 or weight > 1:
                raise ValueError(
                    f"Allocation for {ticker} must be between 0 and 1, got {weight}"
                )

        total = sum(self.allocation.values())
        if not (Decimal("0.999") <= total <= Decimal("1.001")):
            raise ValueError(
                f"Allocation must sum to 1.0 (100%), got {total}"
            )

    def set_allocation(self, allocation: dict[str, float]):
        """Update the target allocation and validate it."""
        self.allocation = self._normalize_allocation(allocation)
        self._validate_allocation()

    def add_holding(self, holding: Holding):
        """Add a holding to the portfolio."""
        existing_tickers = {h.stock.ticker for h in self.holdings}
        if holding.stock.ticker in existing_tickers:
            raise ValueError(f"Duplicate holding for ticker: {holding.stock.ticker}")
        self.holdings.append(holding)

    @property
    def total_value(self) -> Money:
        """Total market value of all holdings plus cash."""
        return sum((h.market_value for h in self.holdings), Decimal("0")) + self.cash

    @property
    def current_weights(self) -> dict[str, Weight]:
        """
        Current weight of each holding as a fraction of total portfolio value.
        Returns 0 for all if portfolio is empty (avoids division by zero).
        """
        total = self.total_value
        if total == 0:
            return {h.stock.ticker: Decimal("0") for h in self.holdings}
        return {h.stock.ticker: h.market_value / total for h in self.holdings}

    def _warn_allocation_coverage(self, holdings_map: dict[str, "Holding"]) -> list[str]:
        """Check for mismatches between allocation and holdings."""
        warnings: list[str] = []
        for ticker, weight in self.allocation.items():
            if ticker not in holdings_map and weight > 0:
                warnings.append(
                    f"{ticker} is in allocation ({weight:.1%}) but not in holdings. "
                    f"Add a zero-share holding with current price to enable trading."
                )
        return warnings

    def rebalance(self, threshold: float = 0.01) -> RebalanceResult:
        """
        Calculate the trades needed to rebalance the portfolio to its target allocation.

        Parameters
        ----------
        threshold : float, default 0.01 (1%)
            Minimum drift (as a fraction) before a trade is generated.
            This avoids unnecessary micro-trades that cost more in fees/taxes
            than the benefit of being perfectly balanced.

            Example: if threshold=0.01, a stock that's 40.5% when target is 40%
            won't trigger a trade (drift = 0.5% < 1%).

        Returns
        -------
        RebalanceResult
            Trades to execute and any warnings. Empty trades list if portfolio
            is already balanced within the threshold.

        How it works
        ------------
        1. Calculate the target value for each stock based on allocation
        2. Compare with current value of each holding
        3. If the difference exceeds the threshold, generate a trade
        4. Holdings not in allocation are liquidated (SELL ALL)
        5. Return trades sorted: SELLs first, then BUYs
           (in practice, you sell first to free up cash for purchases)

        What I Would Add in Production
        ------------------------------
        - Transaction costs: model fees/commissions to avoid trades where cost > benefit
        - Tax-lot optimization: sell specific lots to minimize capital gains tax
        - Settlement timing: T+1/T+2 awareness to avoid buying with unsettled cash
        - Minimum trade sizes: brokers have minimum order sizes; filter sub-minimum trades
        - Market impact: for large positions, split orders to reduce price impact
        """
        threshold = to_decimal(threshold)

        if not self.allocation:
            raise ValueError("No target allocation set. Use set_allocation() first.")

        if not self.holdings:
            raise ValueError("Portfolio has no holdings to rebalance.")

        total = self.total_value
        if total == 0:
            raise ValueError("Portfolio has zero value. Nothing to rebalance.")

        # Build a lookup for current holdings by ticker
        holdings_map: dict[str, Holding] = {
            h.stock.ticker: h for h in self.holdings
        }

        warnings = self._warn_allocation_coverage(holdings_map)
        trades: list[Trade] = []

        # Holdings not in allocation → liquidate (SELL ALL)
        for ticker, holding in holdings_map.items():
            if ticker not in self.allocation and holding.shares > 0:
                trades.append(Trade(
                    ticker=ticker,
                    action=TradeAction.SELL,
                    shares=holding.shares,
                    estimated_value=holding.market_value,
                ))

        for ticker, target_weight in self.allocation.items():
            # What we want this position to be worth
            target_value = total * target_weight

            # What it's currently worth (0 if we don't hold it yet)
            holding = holdings_map.get(ticker)
            current_value = holding.market_value if holding else Decimal("0")

            # How far off are we?
            drift = abs(current_value - target_value) / total

            # Skip if within acceptable threshold
            if drift <= threshold:
                continue

            difference = target_value - current_value

            # We need the stock's current price to calculate shares
            if holding:
                price = holding.stock.current_price
            else:
                # Allocation includes a stock we don't hold — already warned above
                continue

            if price == 0:
                continue  # can't trade a stock with zero price

            shares_to_trade = abs(difference) / price
            action = TradeAction.BUY if difference > 0 else TradeAction.SELL

            trades.append(Trade(
                ticker=ticker,
                action=action,
                shares=shares_to_trade,
                estimated_value=abs(difference),
            ))

        # Sort: SELLs first (free up cash), then BUYs
        trades.sort(key=lambda t: (0 if t.action == TradeAction.SELL else 1, t.ticker))

        return RebalanceResult(trades=trades, warnings=warnings)

    def summary(self) -> str:
        """Human-readable summary of the portfolio state."""
        lines = [
            f"Portfolio Summary",
            f"{'=' * 58}",
            f"Total Value: ${self.total_value:,.2f}  (Cash: ${self.cash:,.2f})",
            f"",
            f"{'Ticker':<8} {'Shares':>10} {'Price':>10} {'Value':>12} {'Weight':>8} {'Target':>8}",
            f"{'-' * 58}",
        ]

        weights = self.current_weights
        for h in self.holdings:
            ticker = h.stock.ticker
            target = self.allocation.get(ticker, Decimal("0"))
            lines.append(
                f"{ticker:<8} {h.shares:>10.2f} {h.stock.current_price:>10.2f} "
                f"{h.market_value:>12.2f} {float(weights[ticker]):>7.1%} {float(target):>7.1%}"
            )

        if self.cash > 0:
            cash_weight = self.cash / self.total_value if self.total_value > 0 else Decimal("0")
            lines.append(
                f"{'CASH':<8} {'':>10} {'':>10} "
                f"{self.cash:>12.2f} {float(cash_weight):>7.1%} {'0.0%':>7}"
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo / Usage Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Create stocks with current prices
    meta = Stock(ticker="META", current_price=585)
    aapl = Stock(ticker="AAPL", current_price=228)
    nvda = Stock(ticker="NVDA", current_price=131)

    # Build portfolio with current holdings and some idle cash
    portfolio = Portfolio(
        holdings=[
            Holding(stock=meta, shares=50),   # $29,250
            Holding(stock=aapl, shares=100),  # $22,800
            Holding(stock=nvda, shares=200),  # $26,200
        ],
        allocation={
            "META": 0.40,   # Target: 40%
            "AAPL": 0.35,   # Target: 35%
            "NVDA": 0.25,   # Target: 25%
        },
        cash=2000,  # $2,000 idle cash to deploy
    )

    # Show current state
    print(portfolio.summary())
    print()

    # Calculate rebalance trades
    result = portfolio.rebalance(threshold=0.01)

    if result.warnings:
        print("Warnings:")
        for w in result.warnings:
            print(f"  ⚠ {w}")
        print()

    if not result.is_balanced:
        print("Rebalancing Trades Needed:")
        print("=" * 58)
        for trade in result.trades:
            print(f"  → {trade}")
        print()
        print(f"  Total buys:  ${result.total_buy_value:,.2f}")
        print(f"  Total sells: ${result.total_sell_value:,.2f}")
        print(f"  Net cash:    ${result.net_cash_flow:,.2f}")
    else:
        print("Portfolio is balanced within threshold. No trades needed.")

    print()

    # Show what "balanced" looks like
    print("After rebalancing, the portfolio would be:")
    total = portfolio.total_value
    for ticker, weight in portfolio.allocation.items():
        print(f"  {ticker}: ${float(total * weight):,.2f} ({float(weight):.0%})")
