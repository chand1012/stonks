FROM python:3.14-slim

# Install uv
RUN pip install uv

WORKDIR /app

# Copy project files for dependency installation
COPY pyproject.toml uv.lock ./

# Install dependencies using uv
RUN uv sync --frozen

# Copy Python source files
COPY main.py screener.py clean_tickers.py config.py ./

COPY tickers.txt ./
COPY ark_tickers.txt ./

# Run the bot
CMD ["uv", "run", "python", "main.py"]
