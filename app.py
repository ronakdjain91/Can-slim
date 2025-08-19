# app.py
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
import json
import os
from utils import (
    fetch_stock_data, calculate_score, run_backtest,
    load_tickers, log_error, ensure_data_file
)
import time

IST = timezone.utc  # Adjust manually in display

st.set_page_config(layout="wide", page_title="CAN SLIM Screener")

# Initialize files
ensure_data_file()

DATA_FILE = 'stock_data.json'
WATCHLIST_FILE = 'watchlist.json'
PORTFOLIO_FILE = 'paper_portfolio.json'

# Load data
@st.cache_data(show_spinner=False)
def load_stock_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
        return data.get('stocks', {})
    except Exception as e:
        log_error("N/A", f"Failed to load stock_data.json: {e}")
        return {}

def load_watchlist():
    try:
        with open(WATCHLIST_FILE, 'r') as f:
            return json.load(f)
    except:
        return []

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, 'w') as f:
        json.dump(watchlist, f)

def load_portfolio():
    try:
        with open(PORTFOLIO_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"cash": 100000.0, "positions": []}

def save_portfolio(portfolio):
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(portfolio, f, indent=2)

# Sidebar
st.sidebar.title("CAN SLIM Screener")

# Manual Refresh
if st.sidebar.button("🔄 Refresh All Data"):
    st.cache_data.clear()
    with st.spinner("Fetching latest data..."):
        fetch_stock_data()
    st.success("Data refreshed!")
    st.cache_data.clear()

# Watchlist Management
st.sidebar.subheader("Watchlist")
watchlist = load_watchlist()
add_ticker = st.sidebar.text_input("Add Ticker (e.g., AAPL)")
if st.sidebar.button("Add to Watchlist") and add_ticker:
    if add_ticker not in watchlist:
        watchlist.append(add_ticker)
        save_watchlist(watchlist)
        st.rerun()

for ticker in watchlist:
    if st.sidebar.button(f"❌ {ticker}"):
        watchlist.remove(ticker)
        save_watchlist(watchlist)
        st.rerun()

# Filters
st.sidebar.subheader("Filters")
market_caps = st.sidebar.multiselect(
    "Market Cap",
    ["Large (> $10B)", "Mid ($2-10B)", "Small (< $2B)"],
    default=["Large (> $10B)", "Mid ($2-10B)"]
)
sectors = st.sidebar.multiselect(
    "Sectors",
    ["Technology", "Healthcare", "Finance", "Consumer", "Energy"],
    default=["Technology"]
)
momentum = st.sidebar.selectbox("Momentum", ["Positive", "Negative", "All"])

# Max tickers for performance
max_tickers = st.sidebar.number_input("Max Tickers to Screen", 50, 750, 100)

# Load data
data = load_stock_data()
if not data:
    st.warning("No stock data available. Click 'Refresh' to fetch data.")
    st.stop()

# Apply watchlist filter
use_watchlist = st.sidebar.checkbox("Use Watchlist Only", value=False)
tickers_to_use = watchlist if use_watchlist else list(data.keys())
tickers_to_use = [t for t in tickers_to_use if t in data]

# Filter by market cap and sector
filtered_tickers = []
for ticker in tickers_to_use[:max_tickers]:
    d = data[ticker]
    fund = d['fundamentals']
    cap = fund.get("market_cap")
    sec = fund.get("sector", "")

    include = False
    if "Large (> $10B)" in market_caps and cap and cap > 10e9:
        include = True
    if "Mid ($2-10B)" in market_caps and cap and 2e9 < cap <= 10e9:
        include = True
    if "Small (< $2B)" in market_caps and cap and cap < 2e9:
        include = True

    if not include:
        continue

    if sec not in sectors:
        continue

    filtered_tickers.append(ticker)

# Scoring with progress bar
st.subheader("Screening Results")
if not filtered_tickers:
    st.warning("No tickers match filters.")
    st.stop()

progress_bar = st.progress(0)
status_text = st.empty()
results = []

for idx, ticker in enumerate(filtered_tickers):
    try:
        d = data[ticker]
        total, f, t = calculate_score(d)
        momentum_ok = True
        if momentum == "Positive" and t < 40:
            continue
        elif momentum == "Negative" and t >= 40:
            continue

        results.append({
            "Ticker": f"[{ticker}](https://www.tradingview.com/symbols/{ticker.replace('.NS', '')}/)",
            "Total Score": total,
            "Fundamental Score": f,
            "Technical Score": t,
            "EPS Growth": f"{d['fundamentals'].get('eps_growth', 0):.1%}" if d['fundamentals'].get('eps_growth') else "N/A",
            "ROE": f"{d['fundamentals'].get('roe', 0):.1%}" if d['fundamentals'].get('roe') else "N/A",
            "Price": f"${d['fundamentals'].get('price', 0):.2f}",
            "Sector": d['fundamentals'].get('sector', 'Unknown')
        })
    except Exception as e:
        log_error(ticker, f"Scoring failed: {e}")
    progress_bar.progress((idx + 1) / len(filtered_tickers))
    status_text.text(f"Processing: {100*(idx+1)/len(filtered_tickers):.1f}%")

progress_bar.empty()
status_text.empty()

# Paginate results
results_df = pd.DataFrame(results)
results_df = results_df.sort_values("Total Score", ascending=False)

items_per_page = 50
total_pages = (len(results_df) // items_per_page) + 1
page = st.selectbox("Page", range(1, total_pages + 1)) - 1
start = page * items_per_page
end = start + items_per_page

st.markdown(
    results_df.iloc[start:end].to_html(escape=False, index=False),
    unsafe_allow_html=True
)

# Select stock for chart
st.subheader("Candlestick Chart")
selected_ticker = st.selectbox("Select Ticker", filtered_tickers)
if selected_ticker:
    stock_data = data[selected_ticker]
    df = pd.DataFrame(stock_data['hist'])
    df['Date'] = pd.to_datetime(df['Date'])

    fig = go.Figure(data=[go.Candlestick(
        x=df['Date'],
        open=df['Open'],
        high=df['High'],
        low=df['Low'],
        close=df['Close']
    )])
    fig.update_layout(title=f"{selected_ticker} - Candlestick Chart", xaxis_title="Date", yaxis_title="Price")
    st.plotly_chart(fig, use_container_width=True)

    # Backtesting
    if st.button("Run Backtest"):
        with st.spinner("Running backtest..."):
            metrics = run_backtest(selected_ticker, stock_data)
            if metrics:
                st.write(f"**CAGR:** {metrics['CAGR']}%")
                st.write(f"**Sharpe Ratio:** {metrics['Sharpe Ratio']}")
                st.write(f"**Max Drawdown:** {metrics['Max Drawdown']}%")
            else:
                st.error("Backtest failed.")

# Paper Trading
st.subheader("Paper Trading Portfolio")
portfolio = load_portfolio()
cash = portfolio['cash']
positions = portfolio['positions']

st.write(f"**Cash:** ${cash:,.2f}")

# Manual buy/sell
col1, col2 = st.columns(2)
with col1:
    buy_ticker = st.text_input("Buy Ticker")
    buy_shares = st.number_input("Shares", 1, 1000, 1)
    if st.button("Buy"):
        price = data.get(buy_ticker, {}).get('fundamentals', {}).get('price')
        if price and price * buy_shares <= cash:
            cost = price * buy_shares
            portfolio['cash'] -= cost
            found = False
            for p in positions:
                if p['ticker'] == buy_ticker:
                    p['shares'] += buy_shares
                    p['avg_price'] = ((p['avg_price'] * (p['shares'] - buy_shares)) + cost) / p['shares']
                    found = True
            if not found:
                positions.append({
                    "ticker": buy_ticker,
                    "shares": buy_shares,
                    "avg_price": price
                })
            portfolio['positions'] = positions
            save_portfolio(portfolio)
            st.success(f"Bought {buy_shares} shares of {buy_ticker}")
            st.rerun()
        else:
            st.error("Insufficient cash or invalid price.")

with col2:
    if positions:
        sell_ticker = st.selectbox("Sell Ticker", [p['ticker'] for p in positions])
        sell_pos = next((p for p in positions if p['ticker'] == sell_ticker), None)
        max_shares = sell_pos['shares'] if sell_pos else 0
        sell_shares = st.number_input("Sell Shares", 1, max_shares, 1)
        if st.button("Sell"):
            price = data.get(sell_ticker, {}).get('fundamentals', {}).get('price')
            if price and sell_pos and sell_shares <= sell_pos['shares']:
                revenue = price * sell_shares
                portfolio['cash'] += revenue
                sell_pos['shares'] -= sell_shares
                if sell_pos['shares'] == 0:
                    positions.remove(sell_pos)
                portfolio['positions'] = positions
                save_portfolio(portfolio)
                st.success(f"Sold {sell_shares} shares of {sell_ticker}")
                st.rerun()
            else:
                st.error("Invalid sell operation.")
    else:
        st.write("No positions to sell.")

# Portfolio Table
if positions:
    pos_data = []
    for p in positions:
        d = data.get(p['ticker'], {})
        curr_price = d.get('fundamentals', {}).get('price', p['avg_price'])
        pl = (curr_price - p['avg_price']) * p['shares']
        pos_data.append({
            "Ticker": p['ticker'],
            "Shares": p['shares'],
            "Avg Price": f"${p['avg_price']:.2f}",
            "Current Price": f"${curr_price:.2f}",
            "P&L": f"${pl:.2f}"
        })
    st.write("### Positions")
    st.table(pos_data)
    total_value = sum((data.get(p['ticker'], {}).get('fundamentals', {}).get('price', p['avg_price']) * p['shares'] for p in positions), cash)
    st.write(f"**Total Portfolio Value:** ${total_value:,.2f}")
