# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python 3.14 swing trading bot using Alpaca API for automated stock analysis and order execution. Uses a pullback-into-moving-average strategy with bracket orders (stop-loss + take-profit).

## Commands

```bash
# Install dependencies
uv sync

# Run the trading bot (default: 14-day calendar exit)
uv run python main.py

# Enable EMA-based exit (10-day EMA by default)
uv run python main.py --ema-exit

# Custom EMA period (21-day)
uv run python main.py --ema-exit --ema-period=21

# Custom calendar-based exit period
uv run python main.py --max-days=7

# Both exit modes together (exit on EITHER condition)
uv run python main.py --ema-exit --ema-period=10 --max-days=14

# EMA-only mode (disable calendar exit)
uv run python main.py --ema-exit --max-days=0

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
├── bot_main() - infinite loop   ├── analyze_stock() - core analysis
├── run_trading_cycle()          ├── SMA/EMA calculations
├── filter_results() - capital   └── Position sizing & risk calc
│   allocation by gain %
├── place_bracket_order()
├── get_positions_older_than()   (calendar-based exit)
└── get_positions_below_ema()    (trend-based exit)
```

**Trading Flow:**
1. Bot runs 3 cycles daily (market open, midday, 30min before close)
2. Checks exit conditions (configurable):
   - Calendar exit: Closes positions held > N days (default: 14)
   - EMA exit: Closes positions where price < X-day EMA (default: 10)
3. Reads tickers from file, runs `analyze_stock()` on each
4. Filters by available capital, sorted by potential gain %
5. Places bracket orders (limit + OCO stop/target)

**Strategy (screener.py:analyze_stock):**
- Trend filter: Price > 200 SMA (uptrend)
- Entry filter: Price 0-3% above 50 SMA (pullback zone)
- Stop loss: 2% below 50 SMA
- Target: 2.5x risk (minimum 2:1 R/R)
- Risk per trade: 0.5% of account

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
- `MAX_DAYS` - Calendar-based exit after N days (default: `14`, `0` to disable)

## Code Style

- Ruff for linting/formatting (configured in pyproject.toml)
- 4-space indentation
- Type hints with `ty` for checking (uses `# ty:ignore` comments where needed)
- Pydantic models for data validation (`TradeIdea` in main.py)
