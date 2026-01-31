import yfinance as yf
import sys
import os

from config import config


def is_stock_active(ticker):
    try:
        stock = yf.Ticker(ticker)
        # Check if we can get any historical data
        hist = stock.history(period="1d")
        return not hist.empty
    except Exception:
        return False


def clean_ticker_file(file_path):
    with open(file_path, "r") as f:
        tickers = [line.strip() for line in f if line.strip()]

    active_tickers = []
    for ticker in tickers:
        if is_stock_active(ticker):
            active_tickers.append(ticker)
        else:
            print(f"Removing inactive ticker: {ticker}")

    # Write back only active tickers
    with open(file_path, "w") as f:
        f.write("\n".join(active_tickers) + "\n")


if __name__ == "__main__":
    # Use command line argument if provided, otherwise use config default
    if len(sys.argv) >= 2:
        file_path = sys.argv[1]
    else:
        file_path = str(config.tickers.file_path)
        print(f"Using default ticker file from config: {file_path}")

    if not os.path.exists(file_path):
        print(f"Error: File {file_path} not found")
        sys.exit(1)

    clean_ticker_file(file_path)
    print("Ticker file updated successfully")
