# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python 3.14 swing trading bot using Alpaca API for automated stock analysis and order execution. Supports both long and short positions using a pullback-into-moving-average strategy with bracket orders (stop-loss + take-profit).

## Commands

```bash
# Install dependencies
uv sync

# Run the trading bot (default: 21-day calendar exit)
uv run python main.py

# Enable EMA-based exit (10-day EMA by default)
uv run python main.py --ema_exit

# Custom EMA period (21-day)
uv run python main.py --ema_exit --ema_period=21

# Custom calendar-based exit period
uv run python main.py --max_days=7

# Both exit modes together (exit on EITHER condition)
uv run python main.py --ema_exit --ema_period=10 --max_days=14

# EMA-only mode (disable calendar exit)
uv run python main.py --ema_exit --max_days=0

# Enable trailing stop (activate at +3% gain, trail by 2%)
uv run python main.py --trailing_stop

# Custom trailing stop settings
uv run python main.py --trailing_stop --trailing_stop_activation=10 --trailing_stop_trail=3

# Combine all exit modes
uv run python main.py --ema_exit --max_days=14 --trailing_stop

# Lint and format
uv run ruff check .
uv run ruff format .

# Type checking
uv run ty check

# Generate tickers from ARK ETF holdings
uv run python gen_tickers.py

# Validate ticker list
uv run python clean_tickers.py

# Docker build
docker build -t stonks .
```

## Architecture

```
main.py (Orchestration)          screener.py (Strategy Engine)
├── bot_main() - infinite loop   ├── analyze_stock() - long & short analysis
├── run_trading_cycle()          ├── SMA/EMA calculations
├── filter_results() - capital   └── Position sizing & risk calc
│   allocation by gain %
├── place_bracket_order()            (handles both long & short)
├── get_positions_older_than()       (calendar-based exit)
├── get_positions_for_ema_exit()     (trend-based exit, side-aware)
├── get_positions_for_trailing_stop() (trailing stop eligibility, side-aware)
└── activate_trailing_stop()         (replace bracket with trailing stop)
```

**Trading Flow:**
1. Bot runs 3 cycles daily (market open, midday, 30min before close)
2. Checks market regime (SPY vs 200 SMA) - adjusts position sizing per direction
3. Checks exit conditions (configurable, works for both longs and shorts):
   - Calendar exit: Closes positions held > N days (default: 21)
   - EMA exit: Closes longs when price < EMA, shorts when price > EMA (default: 10-day)
   - Trailing stop: Activates trailing stop when position gains > X% (default: 3%), trails by Y% (default: 2%)
4. Reads tickers from file, runs `analyze_stock()` on each (scans for both long and short setups)
5. Filters by available capital, sorted by potential gain %
6. Places bracket orders (limit + OCO stop/target) - works for both long and short

**Long Strategy (screener.py:analyze_stock):**
- Trend filter: Price > 200 SMA (uptrend)
- Entry filter: Price 0-5% above 50 SMA (pullback to support)
- Volume filter: Current volume > 20-day average * 1.2
- Stop loss: 2% below 50 SMA
- Target: 1.5x risk

**Short Strategy (screener.py:analyze_stock):**
- Trend filter: Price < 200 SMA (downtrend)
- Entry filter: Price 0-5% below 50 SMA (rally to resistance)
- Volume filter: Current volume > 20-day average * 1.2
- Stop loss: 2% above 50 SMA
- Target: 1.5x risk (below entry)

**Position Sizing by Market Regime:**
- Bull market (SPY > 200 SMA): Longs full size, shorts 50%
- Bear market (SPY < 200 SMA): Shorts full size, longs 50%
- Risk per trade: 0.5% of account (0.25% when trading against regime)

## Key Files

- `main.py` - Bot orchestration, order placement, position management
- `screener.py` - Stock analysis, strategy logic, position sizing
- `tickers.txt` / `ark_tickers.txt` - Input ticker lists
- `gen_tickers.py` - Generates tickers from ARK ETF holdings API
- `clean_tickers.py` - Validates tickers via yfinance

## Environment Variables

Required in `.env`:
- `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` - Trading credentials
- `ALPACA_PAPER` - Set `true` for paper trading, `false` for live
- `TICKER_FILE` - Input file path (default: `tickers.txt`)

Exit mode configuration (CLI flags override these):
- `EMA_EXIT` - Set `true` to enable EMA-based exit
- `EMA_PERIOD` - EMA period for trend-based stop (default: `10`)
- `MAX_DAYS` - Calendar-based exit after N days (default: `21`, `0` to disable)
- `TRAILING_STOP` - Set `true` to enable trailing stop mode
- `TRAILING_STOP_ACTIVATION` - Gain % threshold to activate trailing stop (default: `3.0`)
- `TRAILING_STOP_TRAIL` - Trailing stop percentage (default: `2.0`)

## Code Style

- Ruff for linting/formatting (configured in pyproject.toml)
- 4-space indentation
- Type hints with `ty` for checking (uses `# ty:ignore` comments where needed)
- Pydantic models for data validation (`TradeIdea` in main.py)
