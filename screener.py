# screener.py
import argparse
import sys
import pandas as pd
import yfinance as yf
from rich.console import Console
from rich.table import Table

RISK_PERCENT = 0.005


def calculate_sma(series, window):
    return series.rolling(window=window).mean()


def calculate_ema(series, window):
    """Calculate Exponential Moving Average."""
    return series.ewm(span=window, adjust=False).mean()


def get_current_price_and_ema(
    ticker: str, ema_period: int
) -> tuple[float, float] | None:
    """
    Fetch current price and EMA value for a ticker.

    Args:
        ticker: Stock symbol
        ema_period: EMA period to calculate

    Returns:
        Tuple of (current_price, ema_value) or None if data unavailable
    """
    try:
        # Download enough data for EMA calculation (2x period for stability)
        df = yf.download(
            ticker,
            period=f"{max(ema_period * 2, 30)}d",
            progress=False,
            auto_adjust=True,
        )

        if df.empty or len(df) < ema_period:
            return None

        # Handle yfinance multi-index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(ticker, axis=1, level=1)

        df["EMA"] = calculate_ema(df["Close"], ema_period)

        current_price = float(df["Close"].iloc[-1])
        current_ema = float(df["EMA"].iloc[-1])

        return (current_price, current_ema)

    except Exception:
        return None


def get_market_regime() -> bool:
    """
    Check if SPY is above 200 SMA (bullish regime).

    Returns:
        True if market is bullish (SPY > 200 SMA), False otherwise
    """
    try:
        spy = yf.download("SPY", period="1y", progress=False, auto_adjust=True)

        if spy.empty or len(spy) < 200:
            # If we can't get data, assume bullish to avoid blocking trades
            return True

        # Handle yfinance multi-index columns if present
        if isinstance(spy.columns, pd.MultiIndex):
            spy = spy.xs("SPY", axis=1, level=1)

        current_price = float(spy["Close"].iloc[-1])
        sma_200 = float(spy["Close"].rolling(200).mean().iloc[-1])

        return current_price > sma_200
    except Exception:
        # On error, assume bullish to avoid blocking trades
        return True


def generate_execution_summary(
    ticker, price, stop_loss, target, account_value, risk_multiplier=1.0
):
    """
    Generates the Execution Summary table based on the 1% Risk Rule,
    and includes the Potential Gain percentage.

    Args:
        risk_multiplier: Multiplier for position size (0.5 in bearish market, 1.0 in bullish)
    """
    risk_percent = RISK_PERCENT * risk_multiplier
    max_risk_dollars = account_value * risk_percent

    risk_per_share = price - stop_loss

    # Avoid division by zero or negative risk logic
    if risk_per_share <= 0:
        return None

    # Calculate position size (floor division to get whole shares)
    shares = int(max_risk_dollars // risk_per_share)

    # If account is too small for even 1 share with this risk, skip
    if shares == 0:
        return None

    capital_required = shares * price
    potential_profit = (target - price) * shares
    risk_reward_ratio = (target - price) / (price - stop_loss)

    # --- MODIFICATION START: Calculate Potential Gain (%) ---
    potential_gain_percent = ((target - price) / price) * 100
    # --- MODIFICATION END ---

    # Build the Rich Table
    table = Table(
        title=f"🚀 Trade Setup Found: {ticker}",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="bold white")
    table.add_column("Notes", style="dim")

    table.add_row("Action", "BUY (Limit)", f"Current Price: ${price:.2f}")
    table.add_row(
        "Quantity", f"{shares} Shares", f"Based on {RISK_PERCENT * 100}% Account Risk"
    )
    table.add_row("Entry Price", f"${price:.2f}", "Limit Order")
    table.add_row("Stop Loss", f"${stop_loss:.2f}", "Hard Stop (Below 50SMA)")
    table.add_row("Target Price", f"${target:.2f}", f"{risk_reward_ratio:.2f}R Reward")

    # --- MODIFICATION START: Add Potential Gain to the table ---
    table.add_row(
        "Potential Gain",
        f"{potential_gain_percent:.2f}% (${potential_profit:,.2f})",
        "Profit if Target is hit",
    )
    # --- MODIFICATION END ---

    table.add_row(
        "Total Capital",
        f"${capital_required:,.2f}",
        f"{(capital_required / account_value) * 100:.1f}% of Account",
    )
    table.add_row("Max Loss", f"${shares * risk_per_share:.2f}", "1% of Total Equity")

    return table


def analyze_stock(
    ticker, account_value, console, long_risk_multiplier=1.0, short_risk_multiplier=1.0
):
    """
    Analyze a stock for both long and short opportunities.

    Args:
        ticker: Stock symbol
        account_value: Total account value for position sizing
        console: Rich console for output
        long_risk_multiplier: Position size multiplier for longs (1.0 in bull, 0.5 in bear)
        short_risk_multiplier: Position size multiplier for shorts (0.5 in bull, 1.0 in bear)

    Returns:
        Dict with trade details and 'side' field ('buy' or 'sell'), or None
    """
    try:
        # Download 1 year of data to ensure we have enough for 200 SMA
        df = yf.download(ticker, period="1y", progress=False, auto_adjust=True)

        if df.empty or len(df) < 200:
            return None

        # Handle yfinance multi-index columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df = df.xs(ticker, axis=1, level=1)

        # Calculate Indicators
        df["SMA_50"] = calculate_sma(df["Close"], 50)
        df["SMA_200"] = calculate_sma(df["Close"], 200)

        current_close = float(df["Close"].iloc[-1])
        sma_50 = float(df["SMA_50"].iloc[-1])
        sma_200 = float(df["SMA_200"].iloc[-1])

        # Volume Filter (applies to both long and short)
        avg_volume_20 = df["Volume"].rolling(20).mean().iloc[-1]
        current_volume = df["Volume"].iloc[-1]
        has_volume = current_volume > avg_volume_20 * 1.2

        if not has_volume:
            return None

        # Calculate distance from 50 SMA
        distance_from_50 = (current_close - sma_50) / sma_50

        # --- LONG STRATEGY ---
        # Trend Filter: Price > 200 SMA (uptrend)
        # Entry Filter: Price 0-5% above 50 SMA (pullback to support)
        is_uptrend = current_close > sma_200
        is_long_pullback = 0 < distance_from_50 < 0.05

        if is_uptrend and is_long_pullback:
            # Stop Loss: 2% below 50 SMA
            stop_loss = sma_50 * 0.98
            # Target: 1.5x risk
            risk = current_close - stop_loss
            target = current_close + (risk * 1.5)

            return _build_trade_result(
                ticker=ticker,
                side="buy",
                current_close=current_close,
                stop_loss=stop_loss,
                target=target,
                sma_50=sma_50,
                sma_200=sma_200,
                account_value=account_value,
                risk_multiplier=long_risk_multiplier,
                console=console,
            )

        # --- SHORT STRATEGY ---
        # Trend Filter: Price < 200 SMA (downtrend)
        # Entry Filter: Price 0-5% below 50 SMA (rally to resistance)
        is_downtrend = current_close < sma_200
        is_short_rally = -0.05 < distance_from_50 < 0

        if is_downtrend and is_short_rally:
            # Stop Loss: 2% above 50 SMA
            stop_loss = sma_50 * 1.02
            # Target: 1.5x risk (below entry for shorts)
            risk = stop_loss - current_close
            target = current_close - (risk * 1.5)

            return _build_trade_result(
                ticker=ticker,
                side="sell",
                current_close=current_close,
                stop_loss=stop_loss,
                target=target,
                sma_50=sma_50,
                sma_200=sma_200,
                account_value=account_value,
                risk_multiplier=short_risk_multiplier,
                console=console,
            )

        return None

    except Exception as e:
        console.print(f"[red]Error analyzing {ticker}: {e}[/red]")
        return None


def _build_trade_result(
    ticker: str,
    side: str,
    current_close: float,
    stop_loss: float,
    target: float,
    sma_50: float,
    sma_200: float,
    account_value: float,
    risk_multiplier: float,
    console,
) -> dict | None:
    """Build trade result dict for either long or short trades."""
    risk_percent = RISK_PERCENT * risk_multiplier
    max_risk_dollars = account_value * risk_percent

    # Risk per share (always positive)
    risk_per_share = abs(current_close - stop_loss)

    if risk_per_share <= 0:
        return None

    shares = int(max_risk_dollars // risk_per_share)
    if shares == 0:
        return None

    capital_required = shares * current_close

    # Potential profit (always positive)
    potential_profit = abs(target - current_close) * shares
    risk_reward_ratio = abs(target - current_close) / risk_per_share
    potential_gain_percent = (abs(target - current_close) / current_close) * 100
    max_loss = shares * risk_per_share

    # Determine action label
    action = "BUY (Limit)" if side == "buy" else "SELL SHORT (Limit)"

    # Print summary table
    table = _generate_execution_summary_with_side(
        ticker=ticker,
        side=side,
        price=current_close,
        stop_loss=stop_loss,
        target=target,
        shares=shares,
        capital_required=capital_required,
        potential_profit=potential_profit,
        potential_gain_percent=potential_gain_percent,
        risk_reward_ratio=risk_reward_ratio,
        max_loss=max_loss,
        account_value=account_value,
    )
    console.print(table)
    console.print("\n")

    return {
        "ticker": ticker,
        "side": side,
        "action": action,
        "quantity": shares,
        "entry_price": current_close,
        "stop_loss": stop_loss,
        "target_price": target,
        "potential_gain_percent": potential_gain_percent,
        "potential_profit": potential_profit,
        "risk_reward_ratio": risk_reward_ratio,
        "total_capital": capital_required,
        "capital_percent_of_account": (capital_required / account_value) * 100,
        "max_loss": max_loss,
        "sma_50": sma_50,
        "sma_200": sma_200,
    }


def _generate_execution_summary_with_side(
    ticker: str,
    side: str,
    price: float,
    stop_loss: float,
    target: float,
    shares: int,
    capital_required: float,
    potential_profit: float,
    potential_gain_percent: float,
    risk_reward_ratio: float,
    max_loss: float,
    account_value: float,
) -> Table:
    """Generate execution summary table for long or short trades."""
    if side == "buy":
        emoji = "🚀"
        action = "BUY (Limit)"
        stop_note = "Hard Stop (Below 50SMA)"
    else:
        emoji = "📉"
        action = "SELL SHORT (Limit)"
        stop_note = "Hard Stop (Above 50SMA)"

    table = Table(
        title=f"{emoji} Trade Setup Found: {ticker}",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="bold white")
    table.add_column("Notes", style="dim")

    table.add_row("Action", action, f"Current Price: ${price:.2f}")
    table.add_row(
        "Quantity", f"{shares} Shares", f"Based on {RISK_PERCENT * 100}% Account Risk"
    )
    table.add_row("Entry Price", f"${price:.2f}", "Limit Order")
    table.add_row("Stop Loss", f"${stop_loss:.2f}", stop_note)
    table.add_row("Target Price", f"${target:.2f}", f"{risk_reward_ratio:.2f}R Reward")
    table.add_row(
        "Potential Gain",
        f"{potential_gain_percent:.2f}% (${potential_profit:,.2f})",
        "Profit if Target is hit",
    )
    table.add_row(
        "Total Capital",
        f"${capital_required:,.2f}",
        f"{(capital_required / account_value) * 100:.1f}% of Account",
    )
    table.add_row("Max Loss", f"${max_loss:.2f}", "Based on Account Risk")

    return table


def main():
    parser = argparse.ArgumentParser(
        description="Swing Trade Screener (Pullback Strategy)"
    )
    parser.add_argument("file", help="Path to newline-separated ticker list file")
    parser.add_argument(
        "--account", type=float, required=True, help="Total Account Value in Dollars"
    )

    args = parser.parse_args()
    console = Console()

    console.print(
        f"[bold green]Starting Scan on Account Value: ${args.account:,.2f}[/bold green]\n"
    )

    try:
        with open(args.file, "r") as f:
            tickers = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        console.print("[bold red]Error: Ticker file not found.[/bold red]")
        sys.exit(1)

    results = []
    with console.status("[bold green]Scanning market data...[/bold green]"):
        for ticker in tickers:
            result = analyze_stock(ticker, args.account, console)
            if result:
                results.append(result)

    # sort results by potential gain percent
    results.sort(key=lambda x: x["potential_gain_percent"], reverse=True)

    # print the top 5
    for result in results[:5]:
        console.print(f"[bold green]{result['ticker']}[/bold green]")
        console.print(f"Potential Gain: {result['potential_gain_percent']:.2f}%")
        console.print(f"Potential Profit: {result['potential_profit']:.2f}")
        console.print(f"Risk Reward Ratio: {result['risk_reward_ratio']:.2f}")
        console.print(f"Total Capital: {result['total_capital']:.2f}")
        console.print(
            f"Capital Percent of Account: {result['capital_percent_of_account']:.2f}%"
        )
        console.print(f"Max Loss: {result['max_loss']:.2f}")
        console.print(f"SMA 50: {result['sma_50']:.2f}")
        console.print(f"SMA 200: {result['sma_200']:.2f}")
        console.print("\n")


if __name__ == "__main__":
    main()
