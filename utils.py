import yfinance as yf
import pandas as pd
import backtrader as bt
from datetime import datetime
import numpy as np
import talib

def fetch_stock_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period='1y')
        if hist.empty:
            return None
        hist.reset_index(inplace=True)
        # Fundamental data
        info = stock.info
        fundamentals = {
            'market_cap': info.get('marketCap', 0),
            'sector': info.get('sector', 'Unknown'),
            'eps_growth': info.get('trailingEps', 0),  # Simplified
            'roe': info.get('returnOnEquity', 0),
        }
        # Technical indicators
        hist['RSI'] = talib.RSI(hist['Close'], timeperiod=14)
        hist['MACD'], hist['MACD_Signal'], _ = talib.MACD(hist['Close'])
        return {'hist': hist, 'fundamentals': fundamentals}
    except:
        return None

def calculate_score(ticker, data, market_caps, sectors, momentum):
    if not data:
        return None
    fundamentals = data['fundamentals']
    hist = data['hist']
    
    score = 0
    # Fundamental filters
    market_cap = fundamentals['market_cap'] / 1e9  # Convert to billions
    if 'Large (> $10B)' in market_caps and market_cap > 10:
        score += 2
    elif 'Mid ($2-10B)' in market_caps and 2 <= market_cap <= 10:
        score += 2
    elif 'Small (< $2B)' in market_caps and market_cap < 2:
        score += 2
    
    if fundamentals['sector'] in sectors:
        score += 2
    
    if fundamentals['eps_growth'] > 0.25:
        score += 2
    if fundamentals['roe'] > 0.17:
        score += 1
    
    # Technical filters
    latest = hist.iloc[-1]
    if momentum == 'Positive' and latest['RSI'] > 50 and latest['MACD'] > latest['MACD_Signal']:
        score += 3
    elif momentum == 'Negative' and latest['RSI'] < 50 and latest['MACD'] < latest['MACD_Signal']:
        score += 3
    elif momentum == 'All':
        score += 1
    
    return score

class CANSLIMStrategy(bt.Strategy):
    params = (('stop_loss', 0.07), ('trail_percent', 0.1),)
    
    def __init__(self):
        self.sma200 = bt.indicators.SMA(self.data.close, period=200)
        self.high52 = bt.indicators.Highest(self.data.high, period=252)
    
    def next(self):
        for i, d in enumerate(self.datas):
            if not self.positionsbyname[d._name].size:
                if d.close[0] > self.high52[i][0] and d.close[0] > self.sma200[i][0]:
                    self.buy(data=d, size=100)
            else:
                if d.close[0] < self.positionsbyname[d._name].price * (1 - self.params.stop_loss):
                    self.sell(data=d, size=self.positionsbyname[d._name].size)
                else:
                    self.sell(data=d, size=self.positionsbyname[d._name].size, exectype=bt.Order.StopTrail, trailpercent=self.params.trail_percent)

def run_backtest(tickers, start_date, end_date):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(CANSLIMStrategy)
    cerebro.broker.set_cash(100000)
    
    for ticker in tickers:
        data = bt.feeds.YahooFinanceData(
            dataname=ticker,
            fromdate=start_date,
            todate=end_date
        )
        cerebro.adddata(data)
    
    cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual_return')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
    results = cerebro.run()
    strat = results[0]
    
    # Calculate CAGR
    annual_returns = strat.analyzers.annual_return.get_analysis()
    years = (end_date - start_date).days / 365.25
    if years > 0:
        cagr = (cerebro.broker.getvalue() / 100000) ** (1 / years) - 1
    else:
        cagr = 0
    
    return {
        'cagr': cagr,
        'sharpe': strat.analyzers.sharpe.get_analysis().get('sharperatio', 0),
        'max_drawdown': strat.analyzers.drawdown.get_analysis().get('maxdrawdown', 0) / 100
    }
