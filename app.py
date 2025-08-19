import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import json
from datetime import datetime, timedelta, time as datetime_time
import pytz
from utils import fetch_stock_data, calculate_score, run_backtest
import time
import os

# Cache data fetching to improve performance
@st.cache_data(ttl=3600)  # Cache for 1 hour
def cached_fetch_stock_data(ticker, _cache_buster=0):  # Add cache_buster to force refresh
    return fetch_stock_data(ticker)

st.title('Hybrid Stock Screener & Backtester')

# Timezone for IST
ist = pytz.timezone('Asia/Kolkata')

# Data storage file
data_file = 'stock_data.json'

# Function to check if data needs refresh (every day at 1 AM IST)
def needs_refresh(last_fetch_str):
    if not last_fetch_str:
        return True
    try:
        last_fetch = datetime.fromisoformat(last_fetch_str).astimezone(ist)
        now = datetime.now(ist)
        today_1am = datetime.combine(now.date(), datetime_time(1, 0)).astimezone(ist)
        return last_fetch < today_1am
    except ValueError:
        return True  # If parsing fails, refresh data

# Load stored data if exists
stored_data = {}
if os.path.exists(data_file):
    try:
        with open(data_file, 'r') as f:
            stored_data = json.load(f)
        last_fetch = stored_data.get('last_fetch', None)
    except Exception as e:
        st.error(f'Error loading stock_data.json: {e}')
        with open('errors.log', 'a') as f:
            f.write(f'{datetime.now(ist)}: Error loading stock_data.json: {str(e)}\n')
        last_fetch = None
else:
    last_fetch = None

# Auto-refresh if needed
if needs_refresh(last_fetch):
    st.info('Fetching fresh data as it is stale or first run...')
    # Proceed to fetch (will happen in screening loop)

# Manual refresh button with cache clearing
cache_buster = int(time.time())  # Unique value to bust cache
if st.sidebar.button('Refresh Data Now'):
    last_fetch = None  # Force refresh
    st.cache_data.clear()  # Clear Streamlit cache
    stored_data = {'last_fetch': None, 'stocks': {}}  # Reset stored data
    st.sidebar.success('Data refresh initiated. Cache cleared.')

# Load tickers
try:
    with open('tickers.txt', 'r') as f:
        all_tickers = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    st.error('tickers.txt not found.')
    all_tickers = []

# Load or initialize watchlist
try:
    with open('watchlist.json', 'r') as f:
        watchlist = json.load(f)
except FileNotFoundError:
    watchlist = []
    with open('watchlist.json', 'w') as f:
        json.dump(watchlist, f)

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

# Progress bar and percentage
progress_bar = st.progress(0)
progress_text = st.empty()  # Placeholder for progress percentage
total_tickers = len(tickers_to_screen)
processed = 0

# Flag to determine if we need to fetch fresh data
fetch_fresh = needs_refresh(last_fetch) or last_fetch is None

# Process tickers in batches
for i in range(0, total_tickers, batch_size):
    batch = tickers_to_screen[i:i + batch_size]
    for ticker in batch:
        try:
            if fetch_fresh or ticker not in stored_data.get('stocks', {}):
                data = cached_fetch_stock_data(ticker, cache_buster)
                if data:
                    stored_data.setdefault('stocks', {})[ticker] = data
            else:
                data = stored_data['stocks'][ticker]
            
            if data and isinstance(data['hist'], list) and data['hist']:
                try:
                    hist = pd.DataFrame(data['hist'])
                    required_cols = ['Date', 'Open', 'High', 'Low', 'Close']
                    if not hist.empty and all(col in hist for col in required_cols):
                        score = calculate_score(ticker, data, market_caps, sectors, momentum)
                        if score is not None:
                            results.append({
                                'Ticker': ticker,
                                'Total Score': score['total'],
                                'Fundamental Score': score['fundamental'],
                                'Technical Score': score['technical']
                            })
                    else:
                        raise ValueError(f"Missing required columns for {ticker}")
                except Exception as e:
                    raise ValueError(f"Invalid hist data format for {ticker}: {str(e)}")
            else:
                raise ValueError(f"No valid historical data for {ticker}")
            processed += 1
            progress_percentage = min(processed / total_tickers, 1.0)
            progress_bar.progress(progress_percentage)
            progress_text.text(f'Processing: {progress_percentage * 100:.1f}%')
            time.sleep(0.1)  # Small delay to avoid API rate limits
        except Exception as e:
            st.warning(f'Error processing {ticker}: {e}')
            with open('errors.log', 'a') as f:
                f.write(f'{datetime.now(ist)}: Error processing {ticker}: {str(e)}\n')
            processed += 1
            progress_percentage = min(processed / total_tickers, 1.0)
            progress_bar.progress(progress_percentage)
            progress_text.text(f'Processing: {progress_percentage * 100:.1f}%')

# Save updated data if fetched fresh
if fetch_fresh:
    stored_data['last_fetch'] = datetime.now(ist).isoformat()
    try:
        with open(data_file, 'w') as f:
            json.dump(stored_data, f, default=str)
    except Exception as e:
        st.error(f'Error saving stock_data.json: {e}')
        with open('errors.log', 'a') as f:
            f.write(f'{datetime.now(ist)}: Error saving stock_data.json: {str(e)}\n')

# Display results with pagination
if results:
    df = pd.DataFrame(results)
    df = df.sort_values(by='Total Score', ascending=False)
    
    # Make Ticker clickable to TradingView
    def make_clickable(ticker):
        return f'<a href="https://www.tradingview.com/chart/?symbol={ticker}" target="_blank">{ticker}</a>'
    
    df_styled = df.style.format({'Ticker': make_clickable})
    
    # Pagination
    st.subheader(f'Showing {len(df)} stocks')
    page_size = 50
    page_number = st.number_input('Page', min_value=1, max_value=(len(df) // page_size) + 1, value=1)
    start_idx = (page_number - 1) * page_size
    end_idx = start_idx + page_size
    
    # Display HTML table
    st.markdown(df_styled.hide(axis='index')[start_idx:end_idx].to_html(escape=False), unsafe_allow_html=True)

    # Plot selected stock
    selected_stock = st.selectbox('Select Stock for Chart', df['Ticker'])
    if selected_stock:
        data = stored_data['stocks'].get(selected_stock) or cached_fetch_stock_data(selected_stock, cache_buster)
        if data and isinstance(data['hist'], list) and data['hist']:
            try:
                hist = pd.DataFrame(data['hist'])
                required_cols = ['Date', 'Open', 'High', 'Low', 'Close']
                if not hist.empty and all(col in hist for col in required_cols):
                    fig = go.Figure(data=[
                        go.Candlestick(
                            x=hist['Date'],
                            open=hist['Open'],
                            high=hist['High'],
                            low=hist['Low'],
                            close=hist['Close']
                        )
                    ])
                    fig.update_layout(title=f'{selected_stock} Candlestick Chart', xaxis_title='Date', yaxis_title='Price')
                    st.plotly_chart(fig)
                else:
                    st.error(f'Invalid or missing data for {selected_stock} chart.')
                    with open('errors.log', 'a') as f:
                        f.write(f'{datetime.now(ist)}: Invalid or missing data for {selected_stock} chart\n')
            except Exception as e:
                st.error(f'Error plotting chart for {selected_stock}: {e}')
                with open('errors.log', 'a') as f:
                    f.write(f'{datetime.now(ist)}: Error plotting chart for {selected_stock}: {str(e)}\n')
        else:
            st.error(f'No valid historical data for {selected_stock}.')
            with open('errors.log', 'a') as f:
                f.write(f'{datetime.now(ist)}: No valid historical data for {selected_stock}\n')

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

# Paper Trading Section
st.header('Paper Portfolio')

# Load paper portfolio
paper_file = 'paper_portfolio.json'
try:
    with open(paper_file, 'r') as f:
        portfolio = json.load(f)
except FileNotFoundError:
    portfolio = {'cash': 100000.0, 'positions': []}

# Update portfolio: fetch current prices, check sell conditions
updated_positions = []
for pos in portfolio['positions']:
    try:
        # Fetch 1-day data to get latest price
        current_data = yf.Ticker(pos['ticker']).history(period='1d')
        if current_data.empty:
            updated_positions.append(pos)
            with open('errors.log', 'a') as f:
                f.write(f'{datetime.now(ist)}: Empty