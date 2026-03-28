import os
import time
import requests
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta, timezone

# ==========================================
# 1. DATABASE CONNECTION MANAGER
# ==========================================
def get_engine():
    """Handles connection for both Streamlit and GitHub Actions."""
    try:
        # Try fetching from Streamlit secrets (Local UI mode)
        import streamlit as st
        db_url = st.secrets["connections"]["neon"]["url"]
    except Exception:
        # Fallback to Environment Variables (GitHub Actions headless mode)
        db_url = os.environ.get("DATABASE_URL")
        
    if not db_url:
        raise ValueError("Database URL not found in secrets or environment variables.")
        
    return create_engine(db_url)

# ==========================================
# 2. TELEGRAM NOTIFIER
# ==========================================
def send_telegram_message(message):
    """Sends a message via Telegram Bot using GitHub Secrets."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        print("Telegram credentials missing. Skipping notification.")
        return

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

# ==========================================
# 3. CORE SYNC ENGINE
# ==========================================
def run_sync(headless=False):
    engine = get_engine()
    
    # A. Safely Fetch all symbols from Portfolio, History, and Watchlist
    symbols_list = []
    with engine.connect() as conn:
        for table in ['portfolio', 'history', 'watchlist']:
            try:
                df = pd.read_sql(f"SELECT DISTINCT symbol FROM {table}", conn)
                symbols_list.extend(df['symbol'].tolist())
            except Exception:
                pass # Table might not exist yet, skip gracefully
        
    # Remove duplicates, empty strings, and clean text
    symbols = set([s.strip().upper() for s in symbols_list if s and str(s).strip() not in ('-', 'N/A')])

    if not symbols:
        if not headless:
            import streamlit as st
            st.warning("No symbols found in portfolio, history, or watchlist to sync.")
        return

    # B. Fetch Live Market Data from Chukul API
    updated_data = []
    
    # Define Nepal Timezone for accurate timestamps
    np_tz = timezone(timedelta(hours=5, minutes=45))
    current_np_time = datetime.now(np_tz).strftime("%Y-%m-%d %H:%M")

    # Add a standard browser User-Agent to prevent getting blocked by the API
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    for sym in symbols:
        try:
            url = f"https://chukul.com/api/data/v2/market-summary/bysymbol/?symbol={sym}"
            resp = requests.get(url, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    updated_data.append({
                        "symbol": sym,
                        "ltp": float(item.get("close", 0)),
                        "change": float(item.get("point_change", 0)),
                        "last_updated": current_np_time
                    })
            # Sleep briefly to prevent API rate-limiting/IP Bans
            time.sleep(0.3) 
        except Exception as e:
            print(f"Failed to fetch {sym}: {e}")

    # C. Push Updates to Cache Table (Using High-Speed Bulk Execution)
    if updated_data:
        with engine.begin() as conn:
            # Ensure table exists
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cache (
                    symbol VARCHAR(20) PRIMARY KEY,
                    ltp NUMERIC(10, 2),
                    change NUMERIC(10, 2),
                    last_updated VARCHAR(50)
                )
            """))
            
            # Use SQLAlchemy Bulk Execution (Passing the whole list at once)
            sql = text("""
                INSERT INTO cache (symbol, ltp, change, last_updated) 
                VALUES (:symbol, :ltp, :change, :last_updated)
                ON CONFLICT (symbol) DO UPDATE 
                SET ltp = EXCLUDED.ltp, change = EXCLUDED.change, last_updated = EXCLUDED.last_updated
            """)
            conn.execute(sql, updated_data)
    
    # D. Take Daily Wealth Snapshot
    take_wealth_snapshot(engine)

    # E. Handle Notifications based on environment
    msg = f"✅ *NEPSE Terminal Sync Complete*\n\n📊 Successfully updated market data for {len(updated_data)} symbols and calculated the daily Wealth Snapshot."
    if headless:
        send_telegram_message(msg)
        print("Sync complete. Message sent.")
    else:
        import streamlit as st
        st.success(f"Database successfully synchronized with Chukul API for {len(updated_data)} stocks!")

# ==========================================
# 4. WEALTH SNAPSHOT CALCULATOR (UPGRADED)
# ==========================================
def take_wealth_snapshot(engine):
    """Calculates True Net Worth (Stock Value + TMS Wallet Cash) and logs it."""
    try:
        with engine.connect() as conn:
            try:
                port_df = pd.read_sql("SELECT * FROM portfolio", conn)
                cache_df = pd.read_sql("SELECT * FROM cache", conn)
                tms_df = pd.read_sql("SELECT amount FROM tms_trx", conn) # Fetch TMS Cash
            except Exception:
                return # Tables don't exist yet
            
        if port_df.empty: return

        # 1. Calculate TMS Wallet Balance
        tms_cash_balance = tms_df['amount'].sum() if not tms_df.empty else 0.0

        # 2. Format types
        port_df['qty'] = pd.to_numeric(port_df['qty'])
        port_df['price'] = pd.to_numeric(port_df['price'])
        
        # 3. Calculate Active Holdings WACC (Optimized Pandas)
        buys = port_df[port_df['transaction_type'].str.upper() == 'BUY'].copy()
        sells = port_df[port_df['transaction_type'].str.upper() == 'SELL'].copy()
        
        buys['cost'] = buys['qty'] * buys['price']
        buy_grouped = buys.groupby('symbol').agg({'qty': 'sum', 'cost': 'sum'}).reset_index()
        buy_grouped['wacc'] = buy_grouped['cost'] / buy_grouped['qty']
        
        sell_grouped = sells.groupby('symbol')['qty'].sum().reset_index().rename(columns={'qty': 'sold_qty'})
        
        holdings = pd.merge(buy_grouped, sell_grouped, on='symbol', how='left').fillna(0)
        holdings['net_qty'] = holdings['qty'] - holdings['sold_qty']
        active = holdings[holdings['net_qty'] > 0].copy()
        
        # 4. Match with LTP to find current value
        if not cache_df.empty:
            active = pd.merge(active, cache_df[['symbol', 'ltp']], on='symbol', how='left').fillna(0)
        else:
            active['ltp'] = active['wacc']

        # 5. TRUE WEALTH CALCULATION
        total_invested_in_stocks = (active['net_qty'] * active['wacc']).sum()
        current_stock_value = (active['net_qty'] * active['ltp']).sum()

        # Net Worth = Value of Stocks + Cash resting in TMS
        true_net_worth = current_stock_value + tms_cash_balance

        # Save to DB (Using exact Nepal Time Date)
        np_tz = timezone(timedelta(hours=5, minutes=45))
        today_date = str(datetime.now(np_tz).date())
        
        with engine.begin() as conn:
            sql = text("""
                INSERT INTO wealth (snapshot_date, total_investment, current_value)
                VALUES (:date, :inv, :val)
                ON CONFLICT (snapshot_date) DO UPDATE 
                SET total_investment = EXCLUDED.total_investment, current_value = EXCLUDED.current_value
            """)
            conn.execute(sql, {"date": today_date, "inv": total_invested_in_stocks, "val": true_net_worth})
            
    except Exception as e:
        print(f"Wealth Snapshot Failed: {e}")
