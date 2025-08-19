# utils.py
import yfinance as yf
import pandas as pd
import numpy as np
import pandas_ta as ta
import json
import time
import logging
from datetime import datetime, timezone
import backtrader as bt
import os

IST = timezone.utc  # We'll adjust to IST manually if needed
DATA_FILE = 'stock_data.json'
ERROR_LOG = 'errors.log'

# Configure logging
logging.basicConfig(filename=ERROR_LOG, level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def log_error(ticker: str, message: str):
    """Log error with timestamp and ticker"""
    logging.error(f"{ticker}: {message}")
    with open(ERROR_LOG, 'a') as f:
        f.write(f"{datetime.now(IST)}: {ticker} - {message}\n")

def ensure_data_file():
    """Ensure stock_data.json exists with correct structure"""
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w') as f:
            json.dump({"last_fetch": None, "stocks": {}}, f)
        print("Initialized stock_data.json")

def load_tickers():
    """Load tickers from tickers.txt or return empty list"""
    try:
        with open('tickers.txt', 'r') as f:
            tickers = [line.strip() for line in f if line.strip()]
        return tickers
    except Exception as e:
        log_error("N/A", f"Failed to load tickers.txt: {e}")
        return []

def fetch_single_stock(ticker):
    """Fetch historical and fundamental data for a single ticker"""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2y")
        if hist.empty:
            log_error(ticker, "Empty history from yfinance")
            return None

        # Convert to list of dicts for JSON serialization
        hist.reset_index(inplace=True)
        hist['Date'] = hist['Date'].dt.strftime('%Y-%m-%d')
        hist_data = hist[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']].to_dict('records')

        # Fundamentals
        info = stock.info
        fundamentals = {
            "eps_growth": info.get("earningsQuarterlyGrowth", None),
            "roe": info.get("returnOnEquity", None),
            "market_cap": info.get("marketCap", None),
            "sector": info.get("sector", "Unknown"),
            "pe_ratio": info.get("trailingPE", None),
            "price": info.get("currentPrice") or hist['Close'].iloc[-1],
            "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh", None),
            "twoHundredDayAverage": info.get("twoHundredDayAverage", None)
        }

        # Validate hist is list of dicts
        if not isinstance(hist_data, list) or not all(isinstance(d, dict) for d in hist_data):
            log_error(ticker, "Invalid hist format after conversion")
            return None

        return {
            "hist": hist_data,
            "fundamentals": fundamentals
        }
    except Exception as e:
        log_error(ticker, f"Error fetching data: {e}")
        return None

def fetch_stock_data(max_tickers=None, batch_size=50):
    """Fetch data for all tickers in batches with delay"""
    ensure_data_file()

    tickers = load_tickers()
    if max_tickers:
        tickers = tickers[:max_tickers]

    total = len(tickers)
    results = {}

    for i in range(0, total, batch_size):
        batch = tickers[i:i+batch_size]
        print(f"Processing batch {i//batch_size + 1}")
        for ticker in batch:
            try:
                data = fetch_single_stock(ticker)
                if data:
                    results[ticker] = data
                time.sleep(0.1)  # Rate limit delay
            except Exception as e:
                log_error(ticker, str(e))
                continue

    # Save to file
    try:
        with open(DATA_FILE, 'r') as f:
            file_data = json.load(f)
        file_data['stocks'] = results
        file_data['last_fetch'] = datetime.now(IST).isoformat()
        with open(DATA_FILE, 'w') as f:
            json.dump(file_data, f, indent=2)
    except Exception as e:
        log_error("N/A", f"Failed to save stock_data.json: {e}")

    return results

def calculate_score(data):
    """Calculate CAN SLIM score (fundamental + technical)"""
    try:
        fund = data['fundamentals']
        hist_df = pd.DataFrame(data['hist'])
        if len(hist_df) < 200:
            return 0, 0, 0

        # Technical indicators
        hist_df['rsi'] = ta.rsi(hist_df['Close'], length=14)
        macd = ta.macd(hist_df['Close'])
        hist_df = pd.concat([hist_df, macd], axis=1)
        hist_df['sma_200'] = hist_df['Close'].rolling(200).mean()

        latest = hist_df.iloc[-1]
        prev = hist_df.iloc[-2]

        # Fundamental score
        f_score = 0
        if fund.get("eps_growth", 0) and fund["eps_growth"] > 0.25:
            f_score += 40
        if fund.get("roe", 0) and fund["roe"] > 0.17:
            f_score += 30
        if fund.get("market_cap", 0):
            if fund["market_cap"] > 10e9:
                f_score += 10
            elif fund["market_cap"] > 2e9:
                f_score += 5

        # Technical score
        t_score = 0
        if latest['rsi'] < 70 and prev['rsi'] < 70 and latest['rsi'] > prev['rsi']:
            t_score += 20
        if 'MACD_12_26_9' in latest and 'MACDs_12_26_9' in latest:
            if latest['MACD_12_26_9'] > latest['MACDs_12_26_9']:
                t_score += 20
        if latest['Close'] > latest['sma_200']:
            t_score += 20
        if fund.get("fiftyTwoWeekHigh") and fund.get("price"):
            if fund["price"] >= 0.95 * fund["fiftyTwoWeekHigh"]:
                t_score += 20

        total_score = f_score + t_score
        return total_score, f_score, t_score
    except Exception as e:
        log_error("N/A", f"Error in calculate_score: {e}")
        return 0, 0, 0

# === Backtesting ===

class CANSLIMStrategy(bt.Strategy):
    params = (
        ('stop_loss_percent', 0.07),
        ('trail_percent', 0.10),
    )

    def __init__(self):
        self.data_close = self.datas[0].close
        self.sma_200 = bt.indicators.SMA(self.data_close, period=200)
        self.highest_high = bt.indicators.Highest(self.data_close, period=252)
        self.order = None
        self.buy_price = None

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
            self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.data_close[0] > self.sma_200[0] and self.data_close[0] >= self.highest_high[0]:
                self.buy()
        else:
            if self.data_close[0] <= self.buy_price * (1 - self.p.stop_loss_percent):
                self.sell()
            elif self.data_close[0] <= self.data_close[0] * (1 - self.p.trail_percent):
                self.sell()

def run_backtest(ticker, data):
    """Run backtest using backtrader and return metrics"""
    try:
        df = pd.DataFrame(data['hist'])
        df['datetime'] = pd.to_datetime(df['Date'])
        df.set_index('datetime', inplace=True)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

        if len(df) < 252:
            return None

        data_feed = bt.feeds.PandasData(dataname=df)
        cerebro = bt.Cerebro()
        cerebro.adddata(data_feed)
        cerebro.addstrategy(CANSLIMStrategy)
        cerebro.broker.set_cash(100000.0)
        cerebro.broker.setcommission(commission=0.001)

        initial_value = cerebro.broker.getvalue()
        results = cerebro.run()
        final_value = cerebro.broker.getvalue()

        cagr = ((final_value / initial_value) ** (252/len(df))) - 1
        pnl = cerebro.analyzers.getbyname('pnl')
        returns = [x for x in cerebro.runstrats[0].strat.analyzers.pnl.get_analysis().values()]
        sharpe = bt.analyzers.SharpeRatio()
        max_drawdown = bt.analyzers.DrawDown()

        sharpe_ratio = results[0].analyzers.sharperatio.get_analysis()['sharperatio']
        drawdown = results[0].analyzers.drawdown.get_analysis()['max']['drawdown']

        return {
            'CAGR': round(cagr * 100, 2),
            'Sharpe Ratio': round(sharpe_ratio, 2),
            'Max Drawdown': round(drawdown, 2)
        }
    except Exception as e:
        log_error(ticker, f"Backtest failed: {e}")
        return None
