import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import json
from datetime import datetime, timedelta
from utils import fetch_stock_data, calculate_score, run_backtest
import time

# Cache data fetching to improve performance
@st.cache_data(ttl=3600)  # Cache for 1 hour
def cached_fetch_stock_data(ticker):
    return fetch_stock_data(ticker)

st.title('Hybrid Stock Screener & Backtester')

# Load tickers
with open('tickers.txt', 'r') as f:
    all_tickers = [line.strip() for line in f if line.strip()]

# Load or initialize watchlist
try:
    with open('watchlist.json', 'r') as f:
        watchlist = json.load(f)
except FileNotFoundError:
    watchlist = []

# Sidebar: Filters
st.sidebar.header('Filters')
market_caps = st.sidebar.multiselect(
    'Market Cap', ['Large (> $10B)', 'Mid ($2-10B)', 'Small (< $2B)'],
    default=['Large (> $10B)']
)
sectors = st.sidebar.multiselect(
    'Sectors', ['Technology', 'Healthcare', 'Finance', 'Consumer', 'Energy'],
    default=['Technology']
)
momentum = st.sidebar.selectbox('Momentum', ['Positive', 'Negative', 'All'], index=0)

# Watchlist management
st.sidebar.header('Watchlist Management')
new_stock = st.sidebar.text_input('Add Stock Ticker (e.g., AAPL)')
if st.sidebar.button('Add to Watchlist'):
    if new_stock.upper() in all_tickers and new_stock.upper() not in watchlist:
        watchlist.append(new_stock.upper())
        with open('watchlist.json', 'w') as f:
            json.dump(watchlist, f)
        st.sidebar.success(f'Added {new_stock.upper()} to watchlist')
    elif new_stock.upper() not in all_tickers:
        st.sidebar.error('Invalid ticker')
    else:
        st.sidebar.warning('Stock already in watchlist')

remove_stock = st.sidebar.selectbox('Remove from Watchlist', [''] + watchlist)
if st.sidebar.button('Remove from Watchlist'):
    if remove_stock:
        watchlist.remove(remove_stock)
        with open('watchlist.json', 'w') as f:
            json.dump(watchlist, f)
        st.sidebar.success(f'Removed {remove_stock} from watchlist')

# Filter and score stocks
st.header('Stock Screening Results')
tickers_to_screen = watchlist if watchlist else all_tickers  # Use full ticker list
batch_size = 50  # Process 50 tickers at a time
results = []

# Progress bar
progress_bar = st.progress(0)
total_tickers = len(tickers_to_screen)
processed = 0

# Process tickers in batches
for i in range(0, total_tickers, batch_size):
    batch = tickers_to_screen[i:i + batch_size]
    for ticker in batch:
        try:
            data = cached_fetch_stock_data(ticker)
            if data:
                score = calculate_score(ticker, data, market_caps, sectors, momentum)
                if score is not None:
                    results.append({'Ticker': ticker, 'Score': score})
            processed += 1
            progress_bar.progress(min(processed / total_tickers, 1.0))
            time.sleep(0.1)  # Small delay to avoid API rate limits
        except Exception as e:
            st.warning(f'Error processing {ticker}: {e}')
            processed += 1
            progress_bar.progress(min(processed / total_tickers, 1.0))

# Display results with pagination
if results:
    df = pd.DataFrame(results)
    df = df.sort_values(by='Score', ascending=False)
    
    # Pagination
    st.subheader(f'Showing {len(df)} stocks')
    page_size = 50
    page_number = st.number_input('Page', min_value=1, max_value=(len(df) // page_size) + 1, value=1)
    start_idx = (page_number - 1) * page_size
    end_idx = start_idx + page_size
    st.dataframe(df[start_idx:end_idx])

    # Plot selected stock
    selected_stock = st.selectbox('Select Stock for Chart', df['Ticker'])
    if selected_stock:
        data = cached_fetch_stock_data(selected_stock)
        if data:
            fig = go.Figure(data=[
                go.Candlestick(
                    x=data['hist']['Date'],
                    open=data['hist']['Open'],
                    high=data['hist']['High'],
                    low=data['hist']['Low'],
                    close=data['hist']['Close']
                )
            ])
            fig.update_layout(title=f'{selected_stock} Candlestick Chart', xaxis_title='Date', yaxis_title='Price')
            st.plotly_chart(fig)

# Backtesting Section
st.header('Backtesting')
start_date = st.date_input('Start Date', datetime.now() - timedelta(days=365))
end_date = st.date_input('End Date', datetime.now())
selected_tickers = st.multiselect('Select Tickers for Backtest', df['Ticker'] if results else all_tickers)

if st.button('Run Backtest'):
    if selected_tickers:
        metrics = run_backtest(selected_tickers, start_date, end_date)
        st.write('Backtest Results:')
        st.write(f"CAGR: {metrics['cagr']:.2%}")
        st.write(f"Sharpe Ratio: {metrics['sharpe']:.2f}")
        st.write(f"Max Drawdown: {metrics['max_drawdown']:.2%}")
    else:
        st.warning('Please select at least one ticker for backtesting.')