import requests
import pandas as pd
import numpy as np
import random
import datetime
import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from apscheduler.schedulers.background import BackgroundScheduler
from database import get_db_engine

router = APIRouter()

# --- LOCAL IN-MEMORY STORAGE ---
LOCAL_MARKET_CACHE = {
    "data": {},
    "last_updated": None,
    "status": "Initializing"
}

def is_market_open():
    nepal_tz = pytz.timezone('Asia/Kathmandu')
    now = datetime.datetime.now(nepal_tz)
    is_trading_day = now.weekday() in [6, 0, 1, 2, 3] # Sun-Thu
    start_time = now.replace(hour=10, minute=45, second=0, microsecond=0)
    end_time = now.replace(hour=15, minute=5, second=0, microsecond=0)
    return is_trading_day and (start_time <= now <= end_time)

def update_chukul_local_job(force=False): # Add force parameter
    nepal_tz = pytz.timezone('Asia/Kathmandu')
    
    # Only skip if NOT forced AND market is closed
    if not force and not is_market_open():
        print(f"🕒 [{datetime.datetime.now(nepal_tz).strftime('%H:%M')}] Market Closed. Skipping.")
        LOCAL_MARKET_CACHE["status"] = "Market Closed"
        next_delay = 30 
    else:
        url = "https://chukul.com/api/data/v2/live-market/"
        headers = {"User-Agent": "Mozilla/5.0"}
       try:
            print("🚀 [DEBUG] Fetching Chukul Live Data...")
            response = requests.get(url, headers=headers, timeout=15)
            
            # --- NEW DEBUG LOGS ---
            print(f"📡 [DEBUG] Status Code: {response.status_code}")
            print(f"📡 [DEBUG] Response Headers: {response.headers}")
            
            # Print raw text (truncated to avoid huge logs)
            raw_text = response.text[:1000] 
            print(f"📡 [DEBUG] Raw Response (Partial): {raw_text}")
            # ----------------------

            if response.status_code == 200:
                data = response.json()
                # ... (rest of your logic)
                
                new_prices = {str(item['symbol']).strip().upper(): float(item['ltp']) for item in data}
                LOCAL_MARKET_CACHE["data"] = new_prices
                LOCAL_MARKET_CACHE["last_updated"] = datetime.datetime.now(nepal_tz).strftime("%Y-%m-%d %H:%M:%S")
                LOCAL_MARKET_CACHE["status"] = "Live (Forced)" if force else "Live"
                print(f"✅ Sync Success: {len(new_prices)} symbols.")
            else:
                LOCAL_MARKET_CACHE["status"] = f"API Error {response.status_code}"
        except Exception as e:
            print(f"❌ Fetch Error: {e}")
            LOCAL_MARKET_CACHE["status"] = "Fetch Failed"
        
        next_delay = random.randint(2, 5)

    # Re-schedule the next regular job
    scheduler.add_job(
        func=update_chukul_local_job,
        trigger='date',
        run_date=datetime.datetime.now() + datetime.timedelta(minutes=next_delay),
        id='chukul_sync_job',
        replace_existing=True
    )

scheduler = BackgroundScheduler()
scheduler.add_job(func=update_chukul_local_job, trigger='date', run_date=datetime.datetime.now())
scheduler.start()

# --- NEPSE FEE & TAX CALCULATOR ---
def calculate_net_sell_receivable(ltp, qty, wacc):
    """Calculates exactly how much cash you get after selling at LTP."""
    gross_amount = ltp * qty
    
    # 1. Broker Commission (Standard NEPSE Tiers)
    if gross_amount <= 50000:
        comm_rate = 0.0040 # 0.40%
    elif gross_amount <= 500000:
        comm_rate = 0.0037 # 0.37%
    elif gross_amount <= 2000000:
        comm_rate = 0.0034 # 0.34%
    elif gross_amount <= 10000000:
        comm_rate = 0.0030 # 0.30%
    else:
        comm_rate = 0.0027 # 0.27%
        
    broker_comm = gross_amount * comm_rate
    sebon_fee = gross_amount * 0.00015 # 0.015%
    dp_fee = 25
    
    # Total Selling Cost
    selling_costs = broker_comm + sebon_fee + dp_fee
    net_selling_price = gross_amount - selling_costs
    
    # 2. Capital Gains Tax (CGT) - 7.5% for Individuals
    # CGT is calculated on: (Net Selling Price - Total Purchase Cost)
    total_purchase_cost = wacc * qty
    profit = net_selling_price - total_purchase_cost
    
    cgt_tax = 0
    if profit > 0:
        cgt_tax = profit * 0.075 # 7.5% Tax
        
    final_receivable = net_selling_price - cgt_tax
    return final_receivable, selling_costs + cgt_tax

# --- FINANCIAL LOGIC (FIFO WACC) ---
def calculate_fifo_wacc(df):
    active_holdings = []
    if df.empty: return pd.DataFrame()
    df.columns = [c.lower() for c in df.columns]
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
            active_holdings.append({
                'symbol': symbol.upper().strip(), 
                'net_qty': t_qty, 
                'wacc': t_cost / t_qty, 
                'total_cost': t_cost
            })
    return pd.DataFrame(active_holdings)

# --- THE API ENDPOINT ---
@router.get("/active_portfolio")
def get_active_portfolio(engine = Depends(get_db_engine)):
    try:
        # 1. Fetch Transaction History
        with engine.connect() as conn:
            query = text("SELECT symbol, qty, net_amount, transaction_type, date FROM public.portfolio")
            port_df = pd.read_sql(query, con=conn)
            
        if port_df.empty:
            return {"status": "success", "data": [], "message": "Portfolio is empty."}
        
        # 2. Process FIFO logic
        active_df = calculate_fifo_wacc(port_df)
        
        # 3. Get Live Prices from RAM
        live_prices = LOCAL_MARKET_CACHE["data"]

        # FIX: Use .str accessor to handle the entire column at once
        # Also strip spaces to ensure 'NHPC' matches 'NHPC '
        active_df['lookup_sym'] = active_df['symbol'].astype(str).str.strip().str.upper()
        
        # 4. Map LTP and fallback to WACC
        active_df['ltp'] = active_df['lookup_sym'].map(live_prices).fillna(active_df['wacc'])

        results = []
        total_inv = 0
        total_receivable = 0

        for _, row in active_df.iterrows():
            # Calculate Real-World P/L (Net of Fees & 7.5% CGT)
            receivable, total_exit_fees = calculate_net_sell_receivable(
                float(row['ltp']), 
                int(row['net_qty']), 
                float(row['wacc'])
            )
            
            total_cost = float(row['total_cost'])
            real_pl = receivable - total_cost
            real_pl_pct = (real_pl / total_cost * 100) if total_cost > 0 else 0
            
            total_inv += total_cost
            total_receivable += receivable 

            results.append({
                "symbol": row['symbol'],
                "net_qty": int(row['net_qty']),
                "wacc": round(float(row['wacc']), 2),
                "ltp": round(float(row['ltp']), 2),
                "total_cost": round(total_cost, 2),
                "receivable_val": round(float(receivable), 2), 
                "exit_charges": round(float(total_exit_fees), 2), 
                "real_pl_amt": round(float(real_pl), 2), 
                "real_pl_pct": round(float(real_pl_pct), 2)
            })

        return {
            "status": "success",
            "metadata": {
                "market_status": LOCAL_MARKET_CACHE["status"],
                "last_sync": LOCAL_MARKET_CACHE["last_updated"],
                "server_time": datetime.datetime.now(pytz.timezone('Asia/Kathmandu')).strftime("%H:%M:%S")
            },
            "summary": {
                "total_invested": round(float(total_inv), 2),
                "net_liquid_value": round(float(total_receivable), 2),
                "actual_profit": round(float(total_receivable - total_inv), 2),
                "overall_gain_pct": round(float(((total_receivable - total_inv) / total_inv) * 100) if total_inv > 0 else 0, 2)
            },
            "data": results
        }

    except Exception as e:
        # This will print the EXACT line and error in your Render logs
        print(f"🚨 [CRITICAL API ERROR]: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
