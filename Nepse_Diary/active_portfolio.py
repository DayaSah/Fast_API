import requests
import pandas as pd
import numpy as np
import random
import datetime
import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from apscheduler.schedulers.background import BackgroundScheduler

# Import your database engine from your database.py file
from database import get_db_engine

router = APIRouter()

# --- LOCAL IN-MEMORY STORAGE ---
# This dictionary stays in Render's RAM for instant access
LOCAL_MARKET_CACHE = {
    "data": {},
    "last_updated": None,
    "status": "Initializing"
}

def is_market_open():
    """Checks if current time is Sun-Thu, 10:40 AM - 3:30 PM Nepal Time."""
    nepal_tz = pytz.timezone('Asia/Kathmandu')
    now = datetime.datetime.now(nepal_tz)
    
    # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun
    # NEPSE Trading Days: Sunday to Thursday
    is_trading_day = now.weekday() in [6, 0, 1, 2, 3]
    
    # Define window: 10:40 to 15:30 (Market opens at 11:00, buffer included)
    start_time = now.replace(hour=10, minute=40, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    return is_trading_day and (start_time <= now <= end_time)

def update_chukul_local_job():
    """Fetches LTP only during trading hours with randomized intervals."""
    nepal_tz = pytz.timezone('Asia/Kathmandu')
    
    if not is_market_open():
        print(f"🕒 [{datetime.datetime.now(nepal_tz).strftime('%Y-%m-%d %H:%M')}] Market Closed. Skipping fetch.")
        LOCAL_MARKET_CACHE["status"] = "Market Closed (Using Last Known Prices)"
        # If market is closed, we wait longer to check again (e.g., 30 mins)
        next_delay = 30 
    else:
        url = "https://chukul.com/api/data/v2/live-market/"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        try:
            print(f"🔄 [{datetime.datetime.now(nepal_tz).strftime('%H:%M:%S')}] Fetching Chukul LTP...")
            response = requests.get(url, headers=headers, timeout=12)
            
            if response.status_code == 200:
                data = response.json()
                # Update the RAM dictionary
                new_prices = {item['symbol'].upper(): float(item['ltp']) for item in data}
                LOCAL_MARKET_CACHE["data"] = new_prices
                LOCAL_MARKET_CACHE["last_updated"] = datetime.datetime.now(nepal_tz).strftime("%Y-%m-%d %H:%M:%S")
                LOCAL_MARKET_CACHE["status"] = "Live"
                print(f"✅ Cache Updated. Symbols: {len(new_prices)}")
            else:
                print(f"⚠️ Chukul API returned status: {response.status_code}")
        except Exception as e:
            print(f"❌ Chukul Error: {e}")
        
        # Randomize next fetch between 5 and 10 minutes during market hours
        next_delay = random.randint(5, 10)

    # Schedule the next run dynamically
    scheduler.add_job(
        func=update_chukul_local_job,
        trigger='date',
        run_date=datetime.datetime.now() + datetime.timedelta(minutes=next_delay),
        id='chukul_sync_job',
        replace_existing=True
    )
    print(f"📡 Next sync scheduled in {next_delay} minutes.")

# --- INITIALIZE SCHEDULER ---
scheduler = BackgroundScheduler()
# Trigger the first run immediately on startup
scheduler.add_job(func=update_chukul_local_job, trigger='date', run_date=datetime.datetime.now())
scheduler.start()

# --- ANALYTICS LOGIC (FIFO WACC) ---
def calculate_fifo_wacc(df):
    """Calculates WACC using FIFO for active holdings."""
    active_holdings = []
    if df.empty: return pd.DataFrame()
    
    df['date'] = pd.to_datetime(df['date'])
    for symbol in df['symbol'].unique():
        symbol_df = df[df['symbol'] == symbol].sort_values('date')
        inventory = []
        
        for _, row in symbol_df.iterrows():
            qty = abs(int(row['qty']))
            net_amt = abs(float(row['net_amount']))
            
            if row['transaction_type'].upper() == 'BUY':
                inventory.append({'qty': qty, 'total_cost': net_amt})
            elif row['transaction_type'].upper() == 'SELL':
                rem = qty
                while rem > 0 and inventory:
                    if inventory[0]['qty'] <= rem:
                        rem -= inventory[0]['qty']
                        inventory.pop(0)
                    else:
                        unit_cost = inventory[0]['total_cost'] / inventory[0]['qty']
                        inventory[0]['qty'] -= rem
                        inventory[0]['total_cost'] -= (unit_cost * rem)
                        rem = 0
        
        if inventory:
            t_qty = sum(i['qty'] for i in inventory)
            t_cost = sum(i['total_cost'] for i in inventory)
            if t_qty > 0:
                active_holdings.append({
                    'symbol': symbol.upper(), 
                    'net_qty': t_qty, 
                    'wacc': t_cost / t_qty, 
                    'total_cost': t_cost
                })
    return pd.DataFrame(active_holdings)

# --- THE API ENDPOINT ---
@router.get("/active_portfolio")
def get_active_portfolio(engine = Depends(get_db_engine)):
    try:
        with engine.connect() as conn:
            # 1. Fetch Portfolio History from Neon
            query = text("SELECT symbol, qty, net_amount, transaction_type, date FROM public.portfolio")
            port_df = pd.read_sql(query, con=conn)
            
        if port_df.empty:
            return {"status": "success", "data": [], "message": "Portfolio is empty."}
        
        # 2. Run FIFO Calculation
        port_df.columns = [c.lower() for c in port_df.columns]
        active_df = calculate_fifo_wacc(port_df)
        
        if active_df.empty:
            return {"status": "success", "data": []}

        # 3. Pull LTP from RAM Cache (Instant)
        live_prices = LOCAL_MARKET_CACHE["data"]
        
        # Fallback to WACC if the symbol isn't in the LTP cache yet
        active_df['ltp'] = active_df['symbol'].map(live_prices).fillna(active_df['wacc'])

        # 4. Final Math
        active_df['current_val'] = active_df['net_qty'] * active_df['ltp']
        active_df['pl_amt'] = active_df['current_val'] - active_df['total_cost']
        active_df['pl_pct'] = np.where(active_df['total_cost'] > 0, (active_df['pl_amt'] / active_df['total_cost']) * 100, 0)
        
        total_val = active_df['current_val'].sum()
        active_df['weight'] = np.where(total_val > 0, (active_df['current_val'] / total_val) * 100, 0)
        # NEPSE Breakeven approx: WACC + 0.5% (Comm + SEBON + DP)
        active_df['breakeven'] = (active_df['wacc'] * 1.005) + (25 / active_df['net_qty'])

        # Format for JSON
        data_list = []
        for _, row in active_df.sort_values('symbol').iterrows():
            data_list.append({
                "symbol": row['symbol'],
                "net_qty": int(row['net_qty']),
                "wacc": round(float(row['wacc']), 2),
                "breakeven": round(float(row['breakeven']), 2),
                "ltp": round(float(row['ltp']), 2),
                "total_cost": round(float(row['total_cost']), 2),
                "current_val": round(float(row['current_val']), 2),
                "pl_amt": round(float(row['pl_amt']), 2),
                "pl_pct": round(float(row['pl_pct']), 2),
                "weight": round(float(row['weight']), 2)
            })

        return {
            "status": "success",
            "market_status": LOCAL_MARKET_CACHE["status"],
            "last_sync": LOCAL_MARKET_CACHE["last_updated"],
            "summary": {
                "total_invested": round(float(active_df['total_cost'].sum()), 2),
                "total_current_value": round(float(total_val), 2),
                "total_pl_amt": round(float(active_df['pl_amt'].sum()), 2),
                "total_pl_pct": round(float((active_df['pl_amt'].sum() / active_df['total_cost'].sum() * 100)) if active_df['total_cost'].sum() > 0 else 0, 2)
            },
            "data": data_list
        }

    except Exception as e:
        print(f"🚨 API ERROR: {e}")
        raise HTTPException(status_code=500, detail=str(e))
