# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python 3.14 swing trading bot using Alpaca API for automated stock analysis and order execution. Supports both long and short positions using a pullback-into-moving-average strategy with bracket orders (stop-loss + take-profit).

## Tools

Always use retrieval tools available to you. Always prefer up to date information from these tools over pretrained outdated information. Here is the complete list of tools:

- Web Search (built in to Claude)
  - Lets you search the web for up to date information on any topic
- Fetch (built in to Claude)
  - Lets you fetch information from a URL and return the content.
- Yahoo Finance MCP
  - Lets you get real time stock data for any ticker
- Alpaca MCP
  - Lets you analyze our current portfolio and open positions to determine our current position size and risk exposure.
- Context7 MCP
  - Lets you get the latest documentation for any library, framework, tools, or anything related to the project.

## Commands

```bash
# Install dependencies
uv sync

# Run the trading bot
# All configuration is in config.py or via environment variables
uv run python main.py

# Lint and format
uv run ruff check .
uv run ruff format .

# Type checking
uv run ty check

# Generate tickers from ARK ETF holdings
uv run python gen_tickers.py

# Validate ticker list (uses config default or specify file)
uv run python clean_tickers.py
uv run python clean_tickers.py tickers.txt

# Docker build
docker build -t stonks .

# Verify config loads correctly
uv run python -c "from config import config; print(config)"
```

## Architecture

```
config.py (Central Configuration)
├── AlpacaConfig - API credentials, paper trading mode
├── TickerConfig - Ticker source, file path, ARK funds list
├── ExitConfig - EMA exit, calendar exit, trailing stops
├── EntryConfig - Pullback ranges, stop loss, risk:reward
├── AnalysisConfig - SMA periods, risk percent, regime multipliers
└── BotConfig - Main container, timezone

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
3. Checks exit conditions (all enabled by default, any trigger = exit):
   - **EMA exit**: Closes longs when price < 10 EMA, shorts when price > 10 EMA (trend broken)
   - **Trailing stop (longs)**: Activates at +3% gain, then trails by 5%
   - **Trailing stop (shorts)**: Activates at +2% gain, then trails by 3% (tighter - unlimited loss)
   - **Calendar exit**: Closes positions held > 14 days (prevents dead money)
4. Reads tickers from file, runs `analyze_stock()` on each (scans for both long and short setups)
5. Filters by available capital, sorted by potential gain %
6. Places bracket orders (limit + OCO stop/target) - works for both long and short
7. Trailing stops replace brackets when profit thresholds hit (shorts use tighter params)

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

- `config.py` - **Central configuration** (all settings in one place)
- `main.py` - Bot orchestration, order placement, position management
- `screener.py` - Stock analysis, strategy logic, position sizing
- `tickers.txt` / `ark_tickers.txt` - Input ticker lists
- `gen_tickers.py` - Generates tickers from ARK ETF holdings API
- `clean_tickers.py` - Validates tickers via yfinance

## Configuration

All configuration is centralized in `config.py`. Values can be set directly in the file or overridden via environment variables.

### Config Structure

```python
@dataclass(frozen=True)
class BotConfig:
    alpaca: AlpacaConfig      # API credentials, paper trading
    tickers: TickerConfig     # Ticker source and file path
    exit: ExitConfig          # Exit strategy settings
    entry: EntryConfig        # Entry strategy settings
    analysis: AnalysisConfig  # Analysis parameters
    timezone: str = "US/Eastern"
```

### Environment Variables

Required in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `ALPACA_API_KEY` | Alpaca API key | Required |
| `ALPACA_SECRET_KEY` | Alpaca secret key | Required |
| `ALPACA_PAPER` | Paper trading mode | `true` |

Ticker configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `TICKER_SOURCE` | `file` or `ark_api` | `file` |
| `TICKER_FILE` | Path to ticker list | `tickers.txt` |

Exit configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `EMA_EXIT` | Enable EMA-based exit | `true` |
| `EMA_PERIOD` | EMA period for trend detection | `10` |
| `MAX_DAYS` | Calendar exit after N days (0 to disable) | `14` |
| `TRAILING_STOP` | Enable trailing stop mode | `true` |
| `TRAILING_STOP_ACTIVATION` | Long gain % to activate trailing | `3.0` |
| `TRAILING_STOP_TRAIL` | Long trailing stop % | `5.0` |
| `SHORT_TRAILING_STOP_ACTIVATION` | Short gain % to activate | `2.0` |
| `SHORT_TRAILING_STOP_TRAIL` | Short trailing stop % | `3.0` |

Entry configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `RISK_REWARD_RATIO` | Target profit / risk ratio | `1.5` |
| `VOLUME_FILTER_MULTIPLIER` | Volume filter threshold | `1.2` |

Analysis configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `BASE_RISK_PERCENT` | Risk % per trade | `0.5` |

### Modifying Defaults

To change defaults, edit `config.py` directly. The dataclass defaults serve as the source of truth:

```python
@dataclass(frozen=True)
class ExitConfig:
    ema_exit_enabled: bool = True      # Change default here
    ema_period: int = 10               # Or here
    max_hold_days: int = 14
    # ...
```

## Code Style

- Ruff for linting/formatting (configured in pyproject.toml)
- 4-space indentation
- Type hints with `ty` for checking (uses `# ty:ignore` comments where needed)
- Pydantic models for data validation (`TradeIdea` in main.py)
- Dataclasses with `frozen=True` for immutable configuration
