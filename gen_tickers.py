from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
import httpx

from config import config

stock_historical_data_client = StockHistoricalDataClient(
    config.alpaca.api_key, config.alpaca.secret_key
)

tickers = set[str]()
trading_tickers = set[str]()

for fund in config.tickers.ark_funds:
    response = httpx.get(config.tickers.ark_api_url + fund)
    data = response.json()
    for holding in data["holdings"]:
        ticker: str = holding.get("ticker")
        if ticker and ticker.isalpha():
            tickers.add(ticker.upper())

# check if we can trade on alpaca for each ticker
for ticker in tickers:
    try:
        response = stock_historical_data_client.get_stock_latest_trade(
            StockLatestTradeRequest(symbol_or_symbols=ticker)
        )
        if response[ticker]:
            trading_tickers.add(ticker)
    except Exception as e:
        print(f"Error: {e}")
        continue

with open("ark_tickers.txt", "w") as f:
    for ticker in trading_tickers:
        f.write(ticker + "\n")
