import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import json
from datetime import datetime, timedelta, time as datetime_time  # Explicitly import time from datetime
import pytz
from utils import fetch_stock_data, calculate_score, run_backtest
import time  # For time.sleep
import os

# Cache data fetching to improve performance
@st.cache_data(ttl=3600)  # Cache for 1 hour
def cached_fetch_stock_data(ticker):
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
        last_fetch = None
else:
    last_fetch = None

# Auto-refresh if needed
if needs_refresh(last_fetch):
    st.info('Fetching fresh data as it is stale or first run...')
    # Proceed to fetch (will happen in screening loop)

# Manual refresh button
if st.sidebar.button('Refresh Data Now'):
    last_fetch = None  # Force refresh
    st.sidebar.success('Data refresh initiated.')

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
                data = cached_fetch_stock_data(ticker)
                if data:
                    # Store only necessary data to save space
                    stored_data.setdefault('stocks', {})[ticker] = data
            else:
                data = stored_data['stocks'][ticker]
            
            if data:
                score = calculate_score(ticker, data, market_caps, sectors, momentum)
                if score is not None:
                    results.append({
                        'Ticker': ticker,
                        'Total Score': score['total'],
                        'Fundamental Score': score['fundamental'],
                        'Technical Score': score['technical']
                    })
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
            json.dump(stored_data, f, default=str)  # Handle datetime serialization
    except Exception as e:
        st.error(f'Error saving stock_data.json: {e}')

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
        data = stored_data['stocks'].get(selected_stock) or cached_fetch_stock_data(selected_stock)
        if data:
            # Reconstruct DataFrame for plotting
            hist = pd.DataFrame(data['hist'])
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
            continue
        current_price = current_data['Close'].iloc[-1]
        # Fetch recent data to check technical indicators (for CAN SLIM sell signal)
        recent_data = stored_data['stocks'].get(pos['ticker']) or cached_fetch_stock_data(pos['ticker'])
        if recent_data:
            hist = pd.DataFrame(recent_data['hist'])
            sma200 = talib.SMA(hist['Close'], timeperiod=200).iloc[-1]
            high52 = hist['High'].rolling(window=252).max().iloc[-1]
            # Check sell conditions (stop-loss or no longer meeting CAN SLIM buy criteria)
            if (current_price < pos['buy_price'] * (1 - 0.07) or
                current_price < sma200 or
                current_price < high52):
                # Sell at current price
                sell_value = current_price * pos['shares']
                portfolio['cash'] += sell_value
                st.warning(f'Sold {pos["ticker"]} at ${current_price:.2f} (Stop-loss or CAN SLIM exit)')
            else:
                # Update current price
                pos['current_price'] = current_price
                updated_positions.append(pos)
        else:
            updated_positions.append(pos)
    except Exception as e:
        st.warning(f'Error updating {pos["ticker"]}: {e}')
        with open('errors.log', 'a') as f:
            f.write(f'{datetime.now(ist)}: Error updating {pos["ticker"]}: {str(e)}\n')
        updated_positions.append(pos)

portfolio['positions'] = updated_positions

# Save updated portfolio
try:
    with open(paper_file, 'w') as f:
        json.dump(portfolio, f)
except Exception as e:
    st.error(f'Error saving paper_portfolio.json: {e}')

# Display portfolio
if portfolio['positions']:
    df_port = pd.DataFrame(portfolio['positions'])
    df_port['Current Value'] = df_port['current_price'] * df_port['shares']
    df_port['P&L'] = (df_port['current_price'] - df_port['buy_price']) * df_port['shares']
    df_port['P&L %'] = ((df_port['current_price'] / df_port['buy_price']) - 1) * 100
    st.subheader('Current Positions')
    st.dataframe(df_port[['ticker', 'buy_date', 'buy_price', 'shares', 'current_price', 'Current Value', 'P&L', 'P&L %']])
else:
    st.info('No positions in paper portfolio.')

total_value = portfolio['cash'] + sum(pos.get('current_price', 0) * pos['shares'] for pos in portfolio['positions'])
st.write(f'Cash: ${portfolio["cash"]:.2f}')
st.write(f'Total Portfolio Value: ${total_value:.2f}')

# Add position to paper portfolio
st.subheader('Add Position to Paper Portfolio')
buy_stock = st.selectbox('Select Stock to Buy', df['Ticker'])
buy_shares = st.number_input('Number of Shares', min_value=1, value=100)
if st.button('Buy in Paper Portfolio'):
    try:
        # Check CAN SLIM buy criteria
        data = stored_data['stocks'].get(buy_stock) or cached_fetch_stock_data(buy_stock)
        if not data:
            st.error(f'Unable to fetch data for {buy_stock}.')
        else:
            hist = pd.DataFrame(data['hist'])
            current_price = hist['Close'].iloc[-1]
            sma200 = talib.SMA(hist['Close'], timeperiod=200).iloc[-1]
            high52 = hist['High'].rolling(window=252).max().iloc[-1]
            if current_price > sma200 and current_price > high52:
                cost = current_price * buy_shares
                if cost > portfolio['cash']:
                    st.error('Insufficient cash for purchase.')
                else:
                    portfolio['cash'] -= cost
                    portfolio['positions'].append({
                        'ticker': buy_stock,
                        'buy_date': datetime.now().isoformat(),
                        'buy_price': current_price,
                        'shares': buy_shares,
                        'current_price': current_price
                    })
                    with open(paper_file, 'w') as f:
                        json.dump(portfolio, f)
                    st.success(f'Bought {buy_shares} shares of {buy_stock} at ${current_price:.2f}')
            else:
                st.error(f'{buy_stock} does not meet CAN SLIM buy criteria.')
    except Exception as e:
        st.error(f'Error buying {buy_stock}: {e}')
        with open('errors.log', 'a') as f:
            f.write(f'{datetime.now(ist)}: Error buying {buy_stock}: {str(e)}\n')

# Sell position from paper portfolio
st.subheader('Sell Position from Paper Portfolio')
sell_stock = st.selectbox('Select Stock to Sell', [pos['ticker'] for pos in portfolio['positions']])
sell_shares = st.number_input('Number of Shares to Sell', min_value=1, value=100)
if st.button('Sell in Paper Portfolio'):
    for pos in portfolio['positions']:
        if pos['ticker'] == sell_stock:
            if sell_shares > pos['shares']:
                st.error('Not enough shares to sell.')
                break
            try:
                current_data = yf.Ticker(sell_stock).history(period='1d')
                if current_data.empty:
                    st.error('Unable to fetch current price.')
                    break
                sell_price = current_data['Close'].iloc[-1]
                sell_value = sell_price * sell_shares
                portfolio['cash'] += sell_value
                pos['shares'] -= sell_shares
                if pos['shares'] == 0:
                    portfolio['positions'].remove(pos)
                with open(paper_file, 'w') as f:
                    json.dump(portfolio, f)
                st.success(f'Sold {sell_shares} shares of {sell_stock} at ${sell_price:.2f}')
                break
            except Exception as e:
                st.error(f'Error selling {sell_stock}: {e}')
                with open('errors.log', 'a') as f:
                    f.write(f'{datetime.now(ist)}: Error selling {sell_stock}: {str(e)}\n')
                break
    else:
        st.error('Position not found.')