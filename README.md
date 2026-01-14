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
├── Trend-based: Close when price drops below X-day EMA
└── Trailing stop: Activate when position gains X%, then trail by Y%
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

# Trailing stop configuration (optional)
TRAILING_STOP=false              # Enable trailing stop mode
TRAILING_STOP_ACTIVATION=5.0     # Activate trailing stop at +X% gain
TRAILING_STOP_TRAIL=2.0          # Trail by X% below peak price
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

# Enable trailing stop (activate at +5% gain, trail by 2%)
uv run python main.py --trailing_stop

# Custom trailing stop settings
uv run python main.py --trailing_stop --trailing_stop_activation=10 --trailing_stop_trail=3

# Combine multiple exit modes
uv run python main.py --ema_exit --max_days=14 --trailing_stop

# Full custom configuration
uv run python main.py --ema_exit --ema_period=21 --max_days=7 --trailing_stop --trailing_stop_activation=8 --trailing_stop_trail=2.5
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
| `--trailing_stop` | `TRAILING_STOP` | `false` | Enable trailing stop mode |
| `--trailing_stop_activation` | `TRAILING_STOP_ACTIVATION` | `5.0` | Gain % to activate trailing stop |
| `--trailing_stop_trail` | `TRAILING_STOP_TRAIL` | `2.0` | Trailing stop percentage |

## How the Exit Modes Work

### Calendar-Based Exit (Default)

Closes positions after a set number of days regardless of price action. Simple and predictable.

### Trend-Based Exit (EMA Stop)

Holds positions as long as price stays above the N-day EMA. This lets winners run during strong trends while cutting losers early if momentum fades.

**Example:** With a 10-day EMA stop:

- Stock goes parabolic for 20 days? You stay in the whole ride.
- Stock stalls and drops below EMA on day 6? You exit early and preserve capital.

### Trailing Stop Loss

Activates a trailing stop after a position reaches a specified gain threshold. This locks in profits while giving winners room to run.

**How it works:**

1. **Entry**: Position opens with a standard bracket order (fixed stop-loss at -2% below 50 SMA, take-profit at 2.5x risk)
2. **Monitoring**: Bot checks positions during each trading cycle (3x per day)
3. **Activation**: When a position gains ≥ activation threshold (default: 5%), the bot:
   - Cancels the existing bracket orders
   - Replaces them with a trailing stop order
4. **Trailing**: The stop price automatically adjusts upward as the stock price rises, staying X% (default: 2%) below the peak price
5. **Exit**: Position closes automatically if price drops X% from its highest point

**Example:** With 5% activation threshold and 2% trail:

- Entry at $100 (with initial bracket: stop at $98, target at $105)
- Initial setup: 2.5x risk/reward ratio (risk $2, target $5 gain)
- Stock rises to $105 → Trailing stop ACTIVATES at $102.90 (2% below $105)
- Stock continues to $110 → Stop adjusts to $107.80 (2% below $110)
- Stock pulls back to $107.75 → Position closes, locking in ~7.75% gain
- **Benefit**: Without trailing stop, position would have closed at take-profit target of $105 (+5%)

This mode is ideal for momentum trades where you want to capture extended moves beyond your initial target while protecting gains.

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
