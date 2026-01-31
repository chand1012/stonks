"""
Centralized configuration for the Stonks trading bot.

All configuration values are defined here with sensible defaults.
Environment variables override defaults where applicable.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()


class TickerSource(Enum):
    """Source for loading ticker symbols."""

    FILE = "file"
    ARK_API = "ark_api"


@dataclass(frozen=True)
class AlpacaConfig:
    """Alpaca API credentials and trading mode."""

    api_key: str
    secret_key: str
    paper_trading: bool = True


@dataclass(frozen=True)
class TickerConfig:
    """Configuration for ticker symbol loading."""

    source: TickerSource = TickerSource.FILE
    file_path: Path = Path("tickers.txt")
    ark_funds: tuple[str, ...] = (
        "ARKF",
        "ARKG",
        "ARKK",
        "ARKQ",
        "ARKW",
        "ARKX",
        "PRNT",
        "IZRL",
        "ARKVX",
        "ARKB",
    )
    ark_api_url: str = "https://arkfunds.io/api/v2/etf/holdings?symbol="


@dataclass(frozen=True)
class ExitConfig:
    """Configuration for position exit modes.

    Default settings optimized for aggressive swing trading (2-14 day holds):

    Exit signals (any triggers a close):
    1. EMA breach: Price closes below 10-day EMA = trend broken, exit immediately
    2. Trailing stop: After 3% gain, trail by 5% to lock in profits
    3. Calendar: 14-day max hold prevents dead money

    SHORT POSITIONS use tighter parameters (shorts need faster exits):
    - 2% activation (vs 3% for longs) - lock in profits faster
    - 3% trail (vs 5% for longs) - tighter due to unlimited loss potential
    """

    # EMA exit
    ema_exit_enabled: bool = True
    ema_period: int = 10

    # Calendar exit
    max_hold_days: int = 14

    # Trailing stop (longs)
    trailing_stop_enabled: bool = True
    trailing_stop_activation_pct: float = 3.0
    trailing_stop_trail_pct: float = 5.0

    # Trailing stop (shorts) - tighter defaults
    short_trailing_stop_activation_pct: float = 2.0
    short_trailing_stop_trail_pct: float = 3.0

    @property
    def calendar_exit_enabled(self) -> bool:
        """Calendar exit is enabled if max_hold_days > 0."""
        return self.max_hold_days > 0

    @property
    def any_exit_enabled(self) -> bool:
        """At least one exit mode must be enabled."""
        return (
            self.ema_exit_enabled
            or self.calendar_exit_enabled
            or self.trailing_stop_enabled
        )


@dataclass(frozen=True)
class EntryConfig:
    """Configuration for trade entry conditions."""

    # Long entry
    long_pullback_min_pct: float = 0.0
    long_pullback_max_pct: float = 5.0
    long_stop_loss_pct: float = 2.0

    # Short entry
    short_rally_min_pct: float = 0.0
    short_rally_max_pct: float = 5.0
    short_stop_loss_pct: float = 2.0

    # Common
    risk_reward_ratio: float = 1.5
    volume_filter_multiplier: float = 1.2


@dataclass(frozen=True)
class AnalysisConfig:
    """Configuration for stock analysis parameters."""

    # Moving averages
    sma_trend_period: int = 200
    sma_entry_period: int = 50
    volume_avg_period: int = 20

    # Position sizing
    base_risk_percent: float = 0.5  # 0.5% of account per trade

    # Market regime multipliers
    bull_long_multiplier: float = 1.0
    bull_short_multiplier: float = 0.5
    bear_long_multiplier: float = 0.5
    bear_short_multiplier: float = 1.0


@dataclass(frozen=True)
class BotConfig:
    """Main configuration container for the trading bot."""

    alpaca: AlpacaConfig
    tickers: TickerConfig
    exit: ExitConfig
    entry: EntryConfig
    analysis: AnalysisConfig
    timezone: str = "US/Eastern"


def _parse_bool(value: str | None, default: bool) -> bool:
    """Parse a boolean from environment variable."""
    if value is None:
        return default
    return value.lower() == "true"


def _parse_float(value: str | None, default: float) -> float:
    """Parse a float from environment variable."""
    if value is None:
        return default
    return float(value)


def _parse_int(value: str | None, default: int) -> int:
    """Parse an int from environment variable."""
    if value is None:
        return default
    return int(value)


def load_config() -> BotConfig:
    """Load configuration from environment variables with defaults."""
    alpaca = AlpacaConfig(
        api_key=os.getenv("ALPACA_API_KEY", ""),
        secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        paper_trading=_parse_bool(os.getenv("ALPACA_PAPER"), True),
    )

    ticker_source_str = os.getenv("TICKER_SOURCE", "file").lower()
    ticker_source = (
        TickerSource.ARK_API if ticker_source_str == "ark_api" else TickerSource.FILE
    )

    tickers = TickerConfig(
        source=ticker_source,
        file_path=Path(os.getenv("TICKER_FILE", "tickers.txt")),
    )

    exit_cfg = ExitConfig(
        ema_exit_enabled=_parse_bool(os.getenv("EMA_EXIT"), True),
        ema_period=_parse_int(os.getenv("EMA_PERIOD"), 10),
        max_hold_days=_parse_int(os.getenv("MAX_DAYS"), 14),
        trailing_stop_enabled=_parse_bool(os.getenv("TRAILING_STOP"), True),
        trailing_stop_activation_pct=_parse_float(
            os.getenv("TRAILING_STOP_ACTIVATION"), 3.0
        ),
        trailing_stop_trail_pct=_parse_float(os.getenv("TRAILING_STOP_TRAIL"), 5.0),
        short_trailing_stop_activation_pct=_parse_float(
            os.getenv("SHORT_TRAILING_STOP_ACTIVATION"), 2.0
        ),
        short_trailing_stop_trail_pct=_parse_float(
            os.getenv("SHORT_TRAILING_STOP_TRAIL"), 3.0
        ),
    )

    entry = EntryConfig(
        risk_reward_ratio=_parse_float(os.getenv("RISK_REWARD_RATIO"), 1.5),
        volume_filter_multiplier=_parse_float(
            os.getenv("VOLUME_FILTER_MULTIPLIER"), 1.2
        ),
    )

    analysis = AnalysisConfig(
        base_risk_percent=_parse_float(os.getenv("BASE_RISK_PERCENT"), 0.5),
    )

    return BotConfig(
        alpaca=alpaca,
        tickers=tickers,
        exit=exit_cfg,
        entry=entry,
        analysis=analysis,
    )


# Global config instance
config = load_config()
