# Portfolio Rebalancing System

**Fintual — Software Engineer (Operations / Automation) Challenge**

## What this does

A portfolio rebalancing system that calculates which stocks to buy and sell to match a target allocation. Given current holdings, a target weight distribution, and optional idle cash, it produces a list of actionable trades ordered for execution (sells first, then buys).

## Architecture

```
Stock              → Market data (ticker + price)
Holding            → Portfolio position (stock + shares)
Trade              → Actionable order (ticker + action + shares + value)
Portfolio          → Holdings + allocation + cash → rebalance()
RebalanceResult    → Trades + warnings + computed properties
```

## Design Decisions

Each decision reflects how this system would operate in a real fund environment:

**Decimal instead of float** — All financial calculations use Python's `Decimal`. This isn't premature optimization; with floats, `0.1 + 0.2 != 0.3`. In a robo-advisor processing real money, floating-point drift is a correctness bug. The `to_decimal()` helper converts via `str()` to avoid `Decimal`'s float precision inheritance.

**Structured result, not a flat list** — `rebalance()` returns a `RebalanceResult` with trades, warnings, and computed properties (`total_buy_value`, `net_cash_flow`, `is_balanced`). In operations, you want to inspect a rebalance before executing it — a flat list doesn't give you that.

**TradeAction enum** — `TradeAction(str, Enum)` prevents typos like `"Buy"` or `"BYU"` at the type level. Inheriting from `str` keeps serialization clean (`TradeAction.BUY == "BUY"` is `True`).

**Cash as a first-class concept** — Idle cash is a drag on returns. The rebalancer includes cash in `total_value` so it naturally deploys idle cash toward the target allocation.

**Threshold parameter** — Every trade has costs (fees, slippage, tax events). The threshold avoids micro-trades where the cost exceeds the benefit of being perfectly balanced.

**SELLs before BUYs** — Trades are sorted so you free up cash before purchasing. This mirrors real operations where you can't buy without available cash.

**Validation at construction, not at rebalance time** — Allocation is validated when set, not when `rebalance()` is called. Discovering a misconfigured allocation during market hours is much worse than catching it at configuration time. Tickers are normalized to uppercase, duplicates are rejected, negative shares are caught immediately.

**Mismatch handling** — Holdings not in the target allocation are liquidated. Allocation tickers not in holdings emit a warning (add a zero-share holding to provide price info and enable trading).

## What I Would Add in Production

These are deliberately omitted to keep the solution simple, but they're the next things I'd build:

- **Transaction costs**: model fees/commissions to avoid trades where cost > benefit
- **Tax-lot optimization**: sell specific lots to minimize capital gains
- **Settlement timing**: T+1/T+2 awareness to avoid buying with unsettled cash
- **Minimum trade sizes**: brokers have minimum order sizes
- **Market impact**: for large positions, split orders to reduce price impact

## Run

```bash
# Run the demo
python portfolio.py

# Run tests (47 tests)
python -m pytest test_portfolio.py -v
# or without pytest:
python -m unittest test_portfolio -v
```

## Example Output

```
Portfolio Summary
==========================================================
Total Value: $80,250.00  (Cash: $2,000.00)

Ticker       Shares      Price        Value   Weight   Target
----------------------------------------------------------
META          50.00     585.00     29250.00   36.4%   40.0%
AAPL         100.00     228.00     22800.00   28.4%   35.0%
NVDA         200.00     131.00     26200.00   32.6%   25.0%
CASH                                2000.00    2.5%    0.0%

Rebalancing Trades Needed:
==========================================================
  → SELL 46.8511 shares of NVDA (~$6137.50)
  → BUY 23.1908 shares of AAPL (~$5287.50)
  → BUY 4.8718 shares of META (~$2850.00)

  Total buys:  $8,137.50
  Total sells: $6,137.50
  Net cash:    $-2,000.00
```

Note how the net cash flow is exactly -$2,000 — the sells don't fully cover the buys because the system is deploying the $2,000 of idle cash into the target allocation.

## LLM Usage

As requested in the challenge instructions, I used Claude (Anthropic) to help structure and refine this solution. The conversation is available [here](./llm_conversation.md).

My approach: I described the architecture I wanted and used Claude to help with documentation clarity and test coverage. The core design decisions (Decimal arithmetic, threshold-based rebalancing, trade ordering, cash awareness) are mine — they come from thinking about how a robo-advisor actually operates in production.

## Tech

- Python 3.12+
- No external dependencies — only stdlib (`dataclasses`, `decimal`, `enum`)
- 47 tests covering: validation, rebalancing, edge cases, precision, idempotency
