# refresh_data.py
from utils import fetch_stock_data
import logging

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Starting nightly data refresh...")
    fetch_stock_data()
    print("Data refresh completed.")
