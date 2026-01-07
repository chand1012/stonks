import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import pytz
from dotenv import load_dotenv
from rich.console import Console
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    GetOrdersRequest,
    GetCalendarRequest,
)
from alpaca.trading.enums import OrderSide, OrderClass, TimeInForce, QueryOrderStatus
from pydantic import BaseModel, Field, ConfigDict

from screener import analyze_stock, get_current_price_and_ema

load_dotenv()


class TradeIdea(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ticker: str
    action: Literal["BUY (Limit)"] = "BUY (Limit)"
    quantity: float = Field(..., gt=0)

    entry_price: float
    stop_loss: float
    target_price: float

    potential_gain_percent: float
    potential_profit: float
    risk_reward_ratio: float

    total_capital: float = Field(..., alias="total_capital")
    capital_percent_of_account: float

    max_loss: float
    sma_50: float
    sma_200: float

    def to_dict(self):
        return self.model_dump()


@dataclass
class ExitConfig:
    """Configuration for position exit modes."""

    ema_exit: bool = False
    ema_period: int = 10
    max_days: int = 14

    @property
    def calendar_exit_enabled(self) -> bool:
        """Calendar exit is enabled if max_days > 0."""
        return self.max_days > 0

    @property
    def any_exit_enabled(self) -> bool:
        """At least one exit mode must be enabled."""
        return self.ema_exit or self.calendar_exit_enabled


console = Console()
is_paper = os.getenv("ALPACA_PAPER") == "true"
trading_client = TradingClient(
    os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY"), paper=is_paper
)

EASTERN = pytz.timezone("US/Eastern")
POSITION_MAX_DAYS = 14


def filter_results(
    results: list[TradeIdea], available_capital: float
) -> list[TradeIdea]:
    """
    Filters trade ideas by highest potential gain until capital is exhausted.
    Results should already be sorted by potential_gain_percent descending.
    """
    filtered = []
    remaining_capital = available_capital

    for trade in results:
        if trade.total_capital <= remaining_capital:
            filtered.append(trade)
            remaining_capital -= trade.total_capital

    return filtered


def analyze(ticker_file: str) -> list[TradeIdea]:
    """Analyze tickers from file and return sorted trade ideas."""
    with open(ticker_file, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    console.print(f"[bold green]Analyzing {len(tickers)} tickers[/bold green]")

    account = trading_client.get_account()
    account_value = float(account.buying_power)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]

    results = []
    for ticker in tickers:
        result = analyze_stock(ticker, account_value, console)
        if result:
            results.append(TradeIdea(**result))

    # Sort results by potential gain percent (descending)
    results.sort(key=lambda x: x.potential_gain_percent, reverse=True)

    return results


def get_market_schedule(date: datetime) -> tuple[datetime, datetime] | None:
    """
    Returns (open_time, close_time) for a date, or None if market closed.
    """
    try:
        calendar = trading_client.get_calendar(
            GetCalendarRequest(start=date.date(), end=date.date())
        )
        if not calendar:
            return None

        day = calendar[0]
        # day.open and day.close are already timezone-aware datetime objects
        open_dt = day.open.astimezone(EASTERN)
        close_dt = day.close.astimezone(EASTERN)

        return (open_dt, close_dt)
    except Exception as e:
        console.print(f"[red]Error getting market schedule: {e}[/red]")
        return None


def calculate_run_times(open_time: datetime, close_time: datetime) -> list[datetime]:
    """Returns 3 run times: market open, midday, 30min before close."""
    duration = close_time - open_time
    midday = open_time + duration / 2
    before_close = close_time - timedelta(minutes=30)
    return [open_time, midday, before_close]


def get_available_capital() -> float:
    """Get buying power from account."""
    account = trading_client.get_account()
    return float(account.buying_power)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]


def get_position_entry_date(symbol: str) -> datetime | None:
    """
    Get the entry date for a position by looking at filled orders.
    Returns the earliest fill date for this symbol.
    """
    try:
        orders = trading_client.get_orders(
            GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                symbols=[symbol],
                limit=100,
            )
        )

        # Find the earliest filled BUY order
        buy_orders = [
            o for o in orders if o.side == OrderSide.BUY and o.filled_at is not None  # ty:ignore[possibly-missing-attribute]
        ]

        if not buy_orders:
            return None

        # Sort by filled_at and get the earliest
        buy_orders.sort(key=lambda o: o.filled_at)
        return buy_orders[0].filled_at

    except Exception as e:
        console.print(f"[red]Error getting entry date for {symbol}: {e}[/red]")
        return None


def get_positions_older_than(days: int) -> list:
    """Get positions held longer than specified days."""
    positions = trading_client.get_all_positions()
    cutoff = datetime.now(pytz.UTC) - timedelta(days=days)  # ty:ignore[invalid-argument-type]
    old_positions = []

    for pos in positions:
        entry_date = get_position_entry_date(pos.symbol)  # ty:ignore[possibly-missing-attribute]
        if entry_date and entry_date < cutoff:
            old_positions.append(pos)

    return old_positions


def get_positions_below_ema(ema_period: int) -> list[tuple[str, float, float]]:
    """
    Get positions where current price is below the specified EMA.

    Args:
        ema_period: EMA period to check against

    Returns:
        List of tuples: (symbol, current_price, ema_value)
    """
    positions = trading_client.get_all_positions()
    failing_positions = []

    for pos in positions:
        symbol = pos.symbol  # ty:ignore[possibly-missing-attribute]
        result = get_current_price_and_ema(symbol, ema_period)

        if result is None:
            # Skip if we can't fetch data (don't close on data errors)
            console.print(f"[yellow]Warning: Could not fetch EMA data for {symbol}[/yellow]")
            continue

        current_price, ema_value = result

        if current_price < ema_value:
            failing_positions.append((symbol, current_price, ema_value))

    return failing_positions


def close_position_with_cancel(symbol: str):
    """Cancel all orders for symbol and close position."""
    try:
        # Cancel open orders for this symbol
        orders = trading_client.get_orders(
            GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
        )
        for order in orders:
            try:
                trading_client.cancel_order_by_id(order.id)  # ty:ignore[possibly-missing-attribute]
                console.print(
                    f"[yellow]Cancelled order {order.id} for {symbol}[/yellow]"  # ty:ignore[possibly-missing-attribute]
                )
            except Exception as e:
                console.print(f"[red]Failed to cancel order {order.id}: {e}[/red]")  # ty:ignore[possibly-missing-attribute]

        # Close the position
        trading_client.close_position(symbol)
        console.print(f"[green]Closed position for {symbol}[/green]")

    except Exception as e:
        console.print(f"[red]Failed to close position for {symbol}: {e}[/red]")


def place_bracket_order(trade: TradeIdea) -> bool:
    """Place a bracket order with stop loss and take profit."""
    try:
        order = trading_client.submit_order(
            LimitOrderRequest(
                symbol=trade.ticker,
                qty=int(trade.quantity),
                side=OrderSide.BUY,
                limit_price=round(trade.entry_price, 2),
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                stop_loss=StopLossRequest(stop_price=round(trade.stop_loss, 2)),
                take_profit=TakeProfitRequest(limit_price=round(trade.target_price, 2)),
            )
        )
        console.print(f"[green]Order placed for {trade.ticker}: {order.id}[/green]")  # ty:ignore[possibly-missing-attribute]
        console.print(
            f"  Entry: ${trade.entry_price:.2f}, "
            f"Stop: ${trade.stop_loss:.2f}, "
            f"Target: ${trade.target_price:.2f}"
        )
        return True
    except Exception as e:
        console.print(f"[red]Failed to place order for {trade.ticker}: {e}[/red]")
        return False


def run_trading_cycle(exit_config: ExitConfig):
    """Execute one trading cycle with configurable exit modes."""
    now = datetime.now(EASTERN)
    console.print(f"\n[bold blue]{'=' * 50}[/bold blue]")
    console.print(
        f"[bold blue]Starting trading cycle at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}[/bold blue]"
    )
    console.print(f"[bold blue]{'=' * 50}[/bold blue]\n")

    # Step 1: Check exit conditions
    positions_to_close: set[str] = set()

    # Step 1a: Calendar-based exit (positions held > max_days)
    if exit_config.calendar_exit_enabled:
        console.print(
            f"[bold]Step 1a: Checking for old positions (>{exit_config.max_days} days)...[/bold]"
        )
        old_positions = get_positions_older_than(exit_config.max_days)
        for pos in old_positions:
            symbol = pos.symbol  # ty:ignore[possibly-missing-attribute]
            console.print(
                f"[yellow]Calendar exit triggered for {symbol} (>{exit_config.max_days} days)[/yellow]"
            )
            positions_to_close.add(symbol)
        if not old_positions:
            console.print(f"[dim]No positions older than {exit_config.max_days} days[/dim]")
    else:
        console.print("[dim]Step 1a: Calendar-based exit disabled[/dim]")

    # Step 1b: EMA-based exit (price below EMA)
    if exit_config.ema_exit:
        console.print(
            f"[bold]Step 1b: Checking EMA trend ({exit_config.ema_period}-day)...[/bold]"
        )
        ema_failures = get_positions_below_ema(exit_config.ema_period)
        for symbol, price, ema in ema_failures:
            console.print(
                f"[yellow]EMA exit triggered for {symbol}: "
                f"${price:.2f} < EMA({exit_config.ema_period})=${ema:.2f}[/yellow]"
            )
            positions_to_close.add(symbol)
        if not ema_failures:
            console.print(
                f"[dim]No positions below {exit_config.ema_period}-day EMA[/dim]"
            )
    else:
        console.print("[dim]Step 1b: EMA-based exit disabled[/dim]")

    # Step 1c: Close all positions meeting exit criteria
    if positions_to_close:
        console.print(f"\n[bold]Closing {len(positions_to_close)} position(s)...[/bold]")
        for symbol in positions_to_close:
            close_position_with_cancel(symbol)
    else:
        console.print("[dim]No positions to close[/dim]")

    # Step 2: Get current positions to avoid duplicates
    console.print("\n[bold]Step 2: Getting current positions...[/bold]")
    current_positions = {p.symbol for p in trading_client.get_all_positions()}  # ty:ignore[possibly-missing-attribute]
    if current_positions:
        console.print(f"[dim]Current positions: {', '.join(current_positions)}[/dim]")
    else:
        console.print("[dim]No current positions[/dim]")

    # Step 3: Get available capital
    console.print("\n[bold]Step 3: Checking available capital...[/bold]")
    available_capital = get_available_capital()
    console.print(f"[dim]Available buying power: ${available_capital:,.2f}[/dim]")

    # Step 4: Analyze and filter trade ideas
    console.print("\n[bold]Step 4: Analyzing stocks...[/bold]")
    ticker_file = os.getenv("TICKER_FILE", "tickers.txt")

    try:
        results = analyze(ticker_file)
        console.print(f"[dim]Found {len(results)} potential trade ideas[/dim]")
    except FileNotFoundError:
        console.print(f"[red]Ticker file not found: {ticker_file}[/red]")
        return
    except Exception as e:
        console.print(f"[red]Error analyzing stocks: {e}[/red]")
        return

    # Step 5: Filter by available capital
    console.print("\n[bold]Step 5: Filtering by available capital...[/bold]")
    filtered = filter_results(results, available_capital)
    console.print(
        f"[dim]Filtered to {len(filtered)} trades within capital constraints[/dim]"
    )

    # Step 6: Place orders for new trades (skip if already holding)
    console.print("\n[bold]Step 6: Placing orders...[/bold]")
    orders_placed = 0
    for trade in filtered:
        if trade.ticker not in current_positions:
            if place_bracket_order(trade):
                orders_placed += 1
                # Update current positions to avoid duplicate orders in same cycle
                current_positions.add(trade.ticker)
        else:
            console.print(
                f"[dim]Skipping {trade.ticker}: already holding position[/dim]"
            )

    console.print(
        f"\n[bold green]Trading cycle complete. {orders_placed} new orders placed.[/bold green]"
    )


def sleep_until_tomorrow(now: datetime):
    """Sleep until 4am Eastern next day."""
    tomorrow = (now + timedelta(days=1)).replace(
        hour=4, minute=0, second=0, microsecond=0
    )
    sleep_seconds = (tomorrow - now).total_seconds()
    console.print(
        f"[dim]Sleeping until {tomorrow.strftime('%Y-%m-%d %H:%M:%S %Z')}[/dim]"
    )
    time.sleep(max(sleep_seconds, 60))  # At least 60 seconds


def bot_main(exit_config: ExitConfig):
    """Main bot loop - runs continuously."""
    console.print(f"\n[bold green]{'=' * 50}[/bold green]")
    console.print("[bold green]Swing Trading Bot Started[/bold green]")
    console.print(f"[bold green]{'=' * 50}[/bold green]\n")
    console.print(f"[dim]Paper trading: {is_paper}[/dim]")
    console.print(f"[dim]Ticker file: {os.getenv('TICKER_FILE', 'tickers.txt')}[/dim]")

    # Display exit configuration
    console.print("[dim]Exit modes:[/dim]")
    if exit_config.calendar_exit_enabled:
        console.print(f"[dim]  - Calendar: {exit_config.max_days} days max hold[/dim]")
    if exit_config.ema_exit:
        console.print(f"[dim]  - EMA trend: {exit_config.ema_period}-day EMA[/dim]")
    console.print()

    while True:
        now = datetime.now(EASTERN)

        # Get today's market schedule
        schedule = get_market_schedule(now)

        if schedule is None:
            # Market closed today (weekend/holiday)
            console.print(
                f"[dim]{now.date()}: Market closed today, sleeping until tomorrow[/dim]"
            )
            sleep_until_tomorrow(now)
            continue

        open_time, close_time = schedule
        run_times = calculate_run_times(open_time, close_time)

        console.print(
            f"[dim]Today's schedule - Open: {open_time.strftime('%H:%M')}, Close: {close_time.strftime('%H:%M')}[/dim]"
        )
        console.print(
            f"[dim]Run times: {', '.join(t.strftime('%H:%M') for t in run_times)}[/dim]"
        )

        # Find next run time
        next_run = None
        for rt in run_times:
            if now < rt:
                next_run = rt
                break

        if next_run is None:
            # All runs done for today, sleep until tomorrow
            console.print("[dim]All trading cycles complete for today[/dim]")
            sleep_until_tomorrow(now)
            continue

        # Sleep until next run time
        sleep_seconds = (next_run - now).total_seconds()
        if sleep_seconds > 0:
            console.print(
                f"[dim]Sleeping until next run at {next_run.strftime('%H:%M:%S %Z')} ({sleep_seconds / 60:.1f} minutes)[/dim]"
            )
            time.sleep(sleep_seconds)

        # Execute trading cycle
        run_trading_cycle(exit_config)


def main(
    ema_exit: bool | None = None,
    ema_period: int | None = None,
    max_days: int | None = None,
):
    """
    Swing Trading Bot with configurable exit modes.

    Args:
        ema_exit: Enable EMA-based exit (close when price < EMA)
        ema_period: EMA period for trend-based stop (default: 10)
        max_days: Calendar-based exit after N days (default: 14, 0 to disable)

    Environment variables (CLI overrides these):
        EMA_EXIT: Set to "true" to enable EMA-based exit
        EMA_PERIOD: EMA period for trend-based stop
        MAX_DAYS: Calendar-based exit after N days
    """
    # Read from environment variables, CLI args override
    if ema_exit is None:
        ema_exit = os.getenv("EMA_EXIT", "").lower() == "true"
    if ema_period is None:
        ema_period = int(os.getenv("EMA_PERIOD", "10"))
    if max_days is None:
        max_days = int(os.getenv("MAX_DAYS", "14"))

    exit_config = ExitConfig(
        ema_exit=ema_exit,
        ema_period=ema_period,
        max_days=max_days,
    )

    # Validate at least one exit mode is enabled
    if not exit_config.any_exit_enabled:
        console.print("[red]Error: At least one exit mode must be enabled[/red]")
        console.print("[dim]Use --ema-exit and/or --max-days > 0[/dim]")
        return

    bot_main(exit_config)


if __name__ == "__main__":
    import fire

    fire.Fire(main)
