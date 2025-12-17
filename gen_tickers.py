import os

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from dotenv import load_dotenv
import httpx

load_dotenv()

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

stock_historical_data_client = StockHistoricalDataClient(
    ALPACA_API_KEY, ALPACA_SECRET_KEY
)

endpoint = "https://arkfunds.io/api/v2/etf/holdings?symbol="
funds = [
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
]

tickers = set[str]()
trading_tickers = set[str]()

for fund in funds:
    response = httpx.get(endpoint + fund)
    data = response.json()
    # print(data)
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
