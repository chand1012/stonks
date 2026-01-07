# Stonks

A Python-based swing trading bot that uses technical analysis to find pullback opportunities in trending stocks and automatically executes trades via the Alpaca API.

> **Disclaimer:** This is a hobby project built for learning and experimentation. It is **not financial advice** and comes with **no guarantees of profit**. Trading involves significant risk of loss. Use at your own risk, and never trade with money you can't afford to lose.

## What It Does

The bot runs continuously during market hours, executing a simple but disciplined swing trading strategy:

1. **Finds pullback opportunities** - Scans your watchlist for stocks in an uptrend (above 200 SMA) that have pulled back to their 50 SMA support
2. **Calculates position sizes** - Uses the 0.5% risk rule to determine how many shares to buy based on your account size
3. **Places bracket orders** - Automatically sets entry, stop-loss, and take-profit levels
4. **Manages exits** - Closes positions based on configurable rules (time-based or trend-based)

## The Strategy

```
Entry Criteria:
├── Price > 200 SMA (confirms uptrend)
├── Price within 0-3% of 50 SMA (pullback zone)
└── Minimum 2:1 risk/reward ratio

Risk Management:
├── Stop Loss: 2% below 50 SMA
├── Take Profit: 2.5x risk
└── Position Size: 0.5% account risk per trade

Exit Rules (configurable):
├── Calendar-based: Close after N days (default: 14)
└── Trend-based: Close when price drops below X-day EMA
```

## Quick Start

### Prerequisites

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) package manager
- [Alpaca](https://alpaca.markets/) trading account (paper or live)

### Installation

```bash
git clone https://github.com/chand1012/stonks.git
cd stonks
uv sync
```

### Configuration

Create a `.env` file:

```bash
# Alpaca API credentials
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_PAPER=true  # Set to false for live trading

# Ticker list to scan
TICKER_FILE=tickers.txt

# Exit mode configuration (optional)
EMA_EXIT=false     # Enable EMA-based exits
EMA_PERIOD=10      # EMA period for trend stops
MAX_DAYS=14        # Close positions after N days (0 to disable)
```

### Create Your Watchlist

Add tickers to `tickers.txt` (one per line):

```
AAPL
MSFT
GOOGL
NVDA
AMZN
```

Or generate a watchlist from ARK ETF holdings:

```bash
uv run python gen_tickers.py
```

### Run the Bot

```bash
# Default mode (14-day calendar exit)
uv run python main.py

# Enable trend-based stops (exit when price < 10-day EMA)
uv run python main.py --ema_exit

# Use both exit modes
uv run python main.py --ema_exit --max_days=14

# Custom settings
uv run python main.py --ema_exit --ema_period=21 --max_days=7
```

The bot will:
- Wait for market open
- Run 3 trading cycles per day (open, midday, 30min before close)
- Automatically handle entries, exits, and position management

## Docker

```bash
# Build
docker build -t stonks .

# Run with environment variables
docker run -d \
  -e ALPACA_API_KEY=your_key \
  -e ALPACA_SECRET_KEY=your_secret \
  -e ALPACA_PAPER=true \
  -e EMA_EXIT=true \
  stonks
```

## Project Structure

```
stonks/
├── main.py           # Bot orchestration, order execution, position management
├── screener.py       # Stock analysis, strategy logic, technical indicators
├── gen_tickers.py    # Generate watchlist from ARK ETF holdings
├── clean_tickers.py  # Validate ticker symbols
├── tickers.txt       # Your watchlist
└── .env              # Configuration (not committed)
```

## CLI Reference

| Flag | Environment Variable | Default | Description |
|------|---------------------|---------|-------------|
| `--ema_exit` | `EMA_EXIT` | `false` | Enable EMA-based exit |
| `--ema_period` | `EMA_PERIOD` | `10` | EMA period for trend stops |
| `--max_days` | `MAX_DAYS` | `14` | Calendar exit after N days (0 to disable) |

## How the Exit Modes Work

### Calendar-Based Exit (Default)

Closes positions after a set number of days regardless of price action. Simple and predictable.

### Trend-Based Exit (EMA Stop)

Holds positions as long as price stays above the N-day EMA. This lets winners run during strong trends while cutting losers early if momentum fades.

**Example:** With a 10-day EMA stop:

- Stock goes parabolic for 20 days? You stay in the whole ride.
- Stock stalls and drops below EMA on day 6? You exit early and preserve capital.

## Development

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run ty check
```

## License

The Unlicense. See [LICENSE](LICENSE) for details.

---

**Remember:** Past performance doesn't guarantee future results. This bot will lose money sometimes—that's part of trading. The goal is to have a positive edge over many trades, not to win every time. Start with paper trading, understand the strategy, and only use real money if you're comfortable with the risks.
