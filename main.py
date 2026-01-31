import time
from datetime import datetime, timedelta
from typing import Literal

import pytz
from rich.console import Console
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    LimitOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    TrailingStopOrderRequest,
    GetOrdersRequest,
    GetCalendarRequest,
)
from alpaca.trading.enums import (
    OrderSide,
    OrderClass,
    TimeInForce,
    QueryOrderStatus,
    OrderType,
)
from pydantic import BaseModel, Field, ConfigDict

from config import config
from screener import analyze_stock, get_current_price_and_ema, get_market_regime


class TradeIdea(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ticker: str
    side: Literal["buy", "sell"] = "buy"  # "buy" for long, "sell" for short
    action: Literal["BUY (Limit)", "SELL SHORT (Limit)"] = "BUY (Limit)"
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


console = Console()
trading_client = TradingClient(
    config.alpaca.api_key, config.alpaca.secret_key, paper=config.alpaca.paper_trading
)

EASTERN = pytz.timezone(config.timezone)


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
    """Analyze tickers from file and return sorted trade ideas (both long and short)."""
    with open(ticker_file, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    console.print(f"[bold green]Analyzing {len(tickers)} tickers[/bold green]")

    account = trading_client.get_account()
    account_value = float(account.buying_power)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]

    # Check market regime and adjust position sizing
    # Longs get full size in bull markets, shorts get full size in bear markets
    is_bullish = get_market_regime()
    if is_bullish:
        long_risk_multiplier = config.analysis.bull_long_multiplier
        short_risk_multiplier = config.analysis.bull_short_multiplier
        console.print(
            "[dim]Market regime: Bullish (SPY > 200 SMA) - Full size longs, 50% shorts[/dim]"
        )
    else:
        long_risk_multiplier = config.analysis.bear_long_multiplier
        short_risk_multiplier = config.analysis.bear_short_multiplier
        console.print(
            "[yellow]Market regime: Bearish (SPY < 200 SMA) - 50% longs, full size shorts[/yellow]"
        )

    results = []
    for ticker in tickers:
        result = analyze_stock(
            ticker, account_value, console, long_risk_multiplier, short_risk_multiplier
        )
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
    Works for both long (BUY) and short (SELL) positions.
    """
    try:
        orders = trading_client.get_orders(
            GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                symbols=[symbol],
                limit=100,
            )
        )

        # Find the earliest filled order that opened a position
        # For longs: BUY opens, for shorts: SELL opens
        # We look for both since we don't know position direction here
        opening_orders = [
            o
            for o in orders
            if o.filled_at is not None  # ty:ignore[possibly-missing-attribute]
        ]

        if not opening_orders:
            return None

        # Sort by filled_at and get the earliest
        opening_orders.sort(key=lambda o: o.filled_at)
        return opening_orders[0].filled_at

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


def get_positions_for_ema_exit(ema_period: int) -> list[tuple[str, float, float, str]]:
    """
    Get positions where EMA exit is triggered.
    - Long positions: exit when price < EMA (trend turning bearish)
    - Short positions: exit when price > EMA (trend turning bullish)

    Args:
        ema_period: EMA period to check against

    Returns:
        List of tuples: (symbol, current_price, ema_value, side)
    """
    positions = trading_client.get_all_positions()
    failing_positions = []

    for pos in positions:
        symbol = pos.symbol  # ty:ignore[possibly-missing-attribute]
        qty = float(pos.qty)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]

        # Determine position side: positive qty = long, negative qty = short
        is_long = qty > 0

        result = get_current_price_and_ema(symbol, ema_period)

        if result is None:
            # Skip if we can't fetch data (don't close on data errors)
            console.print(
                f"[yellow]Warning: Could not fetch EMA data for {symbol}[/yellow]"
            )
            continue

        current_price, ema_value = result

        # Long: exit when price drops below EMA
        # Short: exit when price rises above EMA
        if is_long and current_price < ema_value:
            failing_positions.append((symbol, current_price, ema_value, "long"))
        elif not is_long and current_price > ema_value:
            failing_positions.append((symbol, current_price, ema_value, "short"))

    return failing_positions


def get_positions_for_trailing_stop(
    long_activation_percent: float,
    short_activation_percent: float,
) -> list[tuple[str, float, float, float, str]]:
    """
    Get positions that have gained enough to activate trailing stop.
    Uses different thresholds for longs vs shorts (shorts need faster exits).

    Long gain: (current_price - entry_price) / entry_price
    Short gain: (entry_price - current_price) / entry_price

    Args:
        long_activation_percent: Minimum gain % for longs to activate trailing stop
        short_activation_percent: Minimum gain % for shorts (typically lower)

    Returns:
        List of tuples: (symbol, entry_price, current_price, gain_percent, side)
    """
    positions = trading_client.get_all_positions()
    eligible_positions = []

    for pos in positions:
        symbol = pos.symbol  # ty:ignore[possibly-missing-attribute]
        qty = float(pos.qty)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]

        # Determine position side: positive qty = long, negative qty = short
        is_long = qty > 0
        side = "long" if is_long else "short"

        # Get entry price (average price paid)
        entry_price = float(pos.avg_entry_price)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]
        current_price = float(pos.current_price)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]

        # Calculate unrealized gain percentage based on position direction
        if is_long:
            gain_percent = ((current_price - entry_price) / entry_price) * 100
            activation_threshold = long_activation_percent
        else:
            gain_percent = ((entry_price - current_price) / entry_price) * 100
            activation_threshold = short_activation_percent

        if gain_percent >= activation_threshold:
            eligible_positions.append(
                (symbol, entry_price, current_price, gain_percent, side)
            )

    return eligible_positions


def activate_trailing_stop(symbol: str, trail_percent: float) -> bool:
    """
    Replace existing bracket orders with trailing stop for a position.
    Works for both long and short positions.

    Args:
        symbol: Stock symbol
        trail_percent: Trailing stop percentage (e.g., 2.0 for 2%)

    Returns:
        True if trailing stop was activated successfully
    """
    try:
        # Get position quantity (convert from Alpaca's type to int)
        position = trading_client.get_open_position(symbol)
        qty = float(position.qty)  # ty:ignore[possibly-missing-attribute, invalid-argument-type]

        # Determine position side and order side for closing
        # Long (qty > 0): SELL to close
        # Short (qty < 0): BUY to close
        if qty > 0:
            close_side = OrderSide.SELL
            position_type = "LONG"
            abs_qty = int(qty)
        elif qty < 0:
            close_side = OrderSide.BUY
            position_type = "SHORT"
            abs_qty = int(abs(qty))
        else:
            console.print(f"[red]Invalid position quantity for {symbol}: {qty}[/red]")
            return False

        # Cancel all existing orders for this symbol (stop loss, take profit, etc.)
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
                console.print(
                    f"[yellow]Failed to cancel order {order.id}: {e}[/yellow]"
                )  # ty:ignore[possibly-missing-attribute]

        # Place trailing stop order
        # Note: trail_percent expects percentage as decimal (e.g., 2.0 for 2%, not 0.02)
        trailing_stop_order = trading_client.submit_order(
            TrailingStopOrderRequest(
                symbol=symbol,
                qty=abs_qty,
                side=close_side,
                trail_percent=trail_percent,
                time_in_force=TimeInForce.GTC,
            )
        )

        console.print(
            f"[green]Trailing stop activated for {position_type} {symbol}: "
            f"Order {trailing_stop_order.id}, {abs_qty} shares, {trail_percent}% trail[/green]"  # ty:ignore[possibly-missing-attribute]
        )
        return True

    except Exception as e:
        console.print(f"[red]Failed to activate trailing stop for {symbol}: {e}[/red]")
        return False


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
    """Place a bracket order with stop loss and take profit (works for both long and short)."""
    try:
        # Determine order side based on trade direction
        if trade.side == "buy":
            order_side = OrderSide.BUY
            direction_label = "LONG"
        else:
            order_side = OrderSide.SELL
            direction_label = "SHORT"

        order = trading_client.submit_order(
            LimitOrderRequest(
                symbol=trade.ticker,
                qty=int(trade.quantity),
                side=order_side,
                limit_price=round(trade.entry_price, 2),
                time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET,
                stop_loss=StopLossRequest(stop_price=round(trade.stop_loss, 2)),
                take_profit=TakeProfitRequest(limit_price=round(trade.target_price, 2)),
            )
        )
        console.print(
            f"[green]{direction_label} order placed for {trade.ticker}: {order.id}[/green]"
        )  # ty:ignore[possibly-missing-attribute]
        console.print(
            f"  Entry: ${trade.entry_price:.2f}, "
            f"Stop: ${trade.stop_loss:.2f}, "
            f"Target: ${trade.target_price:.2f}"
        )
        return True
    except Exception as e:
        console.print(f"[red]Failed to place order for {trade.ticker}: {e}[/red]")
        return False


def run_trading_cycle():
    """Execute one trading cycle with configurable exit modes."""
    exit_cfg = config.exit

    now = datetime.now(EASTERN)
    console.print(f"\n[bold blue]{'=' * 50}[/bold blue]")
    console.print(
        f"[bold blue]Starting trading cycle at {now.strftime('%Y-%m-%d %H:%M:%S %Z')}[/bold blue]"
    )
    console.print(f"[bold blue]{'=' * 50}[/bold blue]\n")

    # Step 1: Check exit conditions
    positions_to_close: set[str] = set()

    # Step 1a: Calendar-based exit (positions held > max_days)
    if exit_cfg.calendar_exit_enabled:
        console.print(
            f"[bold]Step 1a: Checking for old positions (>{exit_cfg.max_hold_days} days)...[/bold]"
        )
        old_positions = get_positions_older_than(exit_cfg.max_hold_days)
        for pos in old_positions:
            symbol = pos.symbol  # ty:ignore[possibly-missing-attribute]
            console.print(
                f"[yellow]Calendar exit triggered for {symbol} (>{exit_cfg.max_hold_days} days)[/yellow]"
            )
            positions_to_close.add(symbol)
        if not old_positions:
            console.print(
                f"[dim]No positions older than {exit_cfg.max_hold_days} days[/dim]"
            )
    else:
        console.print("[dim]Step 1a: Calendar-based exit disabled[/dim]")

    # Step 1b: EMA-based exit (long: price < EMA, short: price > EMA)
    if exit_cfg.ema_exit_enabled:
        console.print(
            f"[bold]Step 1b: Checking EMA trend ({exit_cfg.ema_period}-day)...[/bold]"
        )
        ema_failures = get_positions_for_ema_exit(exit_cfg.ema_period)
        for symbol, price, ema, side in ema_failures:
            if side == "long":
                console.print(
                    f"[yellow]EMA exit triggered for LONG {symbol}: "
                    f"${price:.2f} < EMA({exit_cfg.ema_period})=${ema:.2f}[/yellow]"
                )
            else:
                console.print(
                    f"[yellow]EMA exit triggered for SHORT {symbol}: "
                    f"${price:.2f} > EMA({exit_cfg.ema_period})=${ema:.2f}[/yellow]"
                )
            positions_to_close.add(symbol)
        if not ema_failures:
            console.print("[dim]No positions triggered EMA exit[/dim]")
    else:
        console.print("[dim]Step 1b: EMA-based exit disabled[/dim]")

    # Step 1c: Trailing stop activation (positions that hit gain threshold)
    # Shorts use tighter thresholds (faster exits due to unlimited loss potential)
    if exit_cfg.trailing_stop_enabled:
        console.print(
            f"[bold]Step 1c: Checking for trailing stop activation "
            f"(longs >{exit_cfg.trailing_stop_activation_pct}%, "
            f"shorts >{exit_cfg.short_trailing_stop_activation_pct}%)...[/bold]"
        )
        eligible_positions = get_positions_for_trailing_stop(
            exit_cfg.trailing_stop_activation_pct,
            exit_cfg.short_trailing_stop_activation_pct,
        )

        activated_count = 0
        for (
            symbol,
            entry_price,
            current_price,
            gain_percent,
            side,
        ) in eligible_positions:
            position_type = "LONG" if side == "long" else "SHORT"

            # Use tighter trail for shorts (unlimited loss potential)
            if side == "long":
                trail_percent = exit_cfg.trailing_stop_trail_pct
            else:
                trail_percent = exit_cfg.short_trailing_stop_trail_pct

            console.print(
                f"[cyan]{position_type} {symbol} eligible for trailing stop: "
                f"${entry_price:.2f} -> ${current_price:.2f} "
                f"(+{gain_percent:.2f}%, will trail {trail_percent}%)[/cyan]"
            )

            # Check if this position already has a trailing stop
            # (We'll only activate once per position)
            orders = trading_client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])
            )
            has_trailing_stop = any(
                order.type == OrderType.TRAILING_STOP  # ty:ignore[possibly-missing-attribute]
                for order in orders
            )

            if not has_trailing_stop:
                if activate_trailing_stop(symbol, trail_percent):
                    activated_count += 1
            else:
                console.print(f"[dim]  {symbol} already has trailing stop[/dim]")

        if not eligible_positions:
            console.print(
                f"[dim]No positions with >{exit_cfg.trailing_stop_activation_pct}% gain[/dim]"
            )
        elif activated_count > 0:
            console.print(
                f"[green]Activated trailing stops for {activated_count} position(s)[/green]"
            )
    else:
        console.print("[dim]Step 1c: Trailing stop mode disabled[/dim]")

    # Step 1d: Close all positions meeting exit criteria
    if positions_to_close:
        console.print(
            f"\n[bold]Closing {len(positions_to_close)} position(s)...[/bold]"
        )
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
    ticker_file = str(config.tickers.file_path)

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


def bot_main():
    """Main bot loop - runs continuously."""
    exit_cfg = config.exit

    console.print(f"\n[bold green]{'=' * 50}[/bold green]")
    console.print("[bold green]Swing Trading Bot Started[/bold green]")
    console.print(f"[bold green]{'=' * 50}[/bold green]\n")
    console.print(f"[dim]Paper trading: {config.alpaca.paper_trading}[/dim]")
    console.print(f"[dim]Ticker file: {config.tickers.file_path}[/dim]")

    # Display exit configuration
    console.print("[dim]Exit modes:[/dim]")
    if exit_cfg.calendar_exit_enabled:
        console.print(
            f"[dim]  - Calendar: {exit_cfg.max_hold_days} days max hold[/dim]"
        )
    if exit_cfg.ema_exit_enabled:
        console.print(f"[dim]  - EMA trend: {exit_cfg.ema_period}-day EMA[/dim]")
    if exit_cfg.trailing_stop_enabled:
        console.print(
            f"[dim]  - Trailing stop (longs): Activate at +{exit_cfg.trailing_stop_activation_pct}%, "
            f"trail {exit_cfg.trailing_stop_trail_pct}%[/dim]"
        )
        console.print(
            f"[dim]  - Trailing stop (shorts): Activate at +{exit_cfg.short_trailing_stop_activation_pct}%, "
            f"trail {exit_cfg.short_trailing_stop_trail_pct}%[/dim]"
        )
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
        run_trading_cycle()


def main():
    """Entry point for the trading bot."""
    # Validate at least one exit mode is enabled
    if not config.exit.any_exit_enabled:
        console.print("[red]Error: At least one exit mode must be enabled[/red]")
        console.print(
            "[dim]Set EMA_EXIT=true, MAX_DAYS > 0, and/or TRAILING_STOP=true in your .env file[/dim]"
        )
        return

    bot_main()


if __name__ == "__main__":
    main()
