from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import pandas as pd
import numpy as np
import requests
from database import get_db_engine

router = APIRouter()

def get_live_prices_with_fallback(conn):
    """
    PRIMARY: Fetch from Chukul API.
    SECONDARY: If Chukul fails, fetch from public.cache (Database).
    """
    url = "https://chukul.com/api/data/v2/live-market/"
    headers = {"User-Agent": "Mozilla/5.0"}
    
    # 1. TRY CHUKUL (Primary)
    try:
        print("🌐 Attempting to fetch live prices from Chukul...")
        response = requests.get(url, headers=headers, timeout=5) # Short timeout
        if response.status_code == 200:
            data = response.json()
            print("✅ Chukul Success.")
            return {item['symbol'].upper(): float(item['ltp']) for item in data}
    except Exception as e:
        print(f"⚠️ Chukul failed ({e}). Falling back to Database Cache...")

    # 2. FALLBACK TO DB CACHE (Secondary)
    try:
        cache_query = text("SELECT symbol, ltp FROM public.cache")
        cache_df = pd.read_sql(cache_query, con=conn)
        if not cache_df.empty:
            cache_df.columns = [c.lower() for c in cache_df.columns]
            print("📦 Successfully loaded prices from Database Cache.")
            return dict(zip(cache_df['symbol'].str.upper(), cache_df['ltp'].astype(float)))
    except Exception as db_e:
        print(f"❌ Database Cache also failed: {db_e}")
    
    return {}

def calculate_fifo_wacc(df):
    """ Standard NEPSE FIFO Calculation Logic """
    active_holdings = []
    if df.empty: return pd.DataFrame(active_holdings)
    
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

@router.get("/active_portfolio")
def get_active_portfolio(engine = Depends(get_db_engine)):
    try:
        with engine.connect() as conn:
            # 1. Fetch Portfolio
            port_df = pd.read_sql(text("SELECT symbol, qty, net_amount, transaction_type, date FROM public.portfolio"), con=conn)
            
            if port_df.empty:
                return {"status": "success", "data": []}
            
            port_df.columns = [c.lower() for c in port_df.columns]
            active_df = calculate_fifo_wacc(port_df)

            # 2. Get Prices using the new Fallback Function
            live_prices = get_live_prices_with_fallback(conn)
        
        # 3. Integrate Prices (Fallback to WACC if both Chukul & Cache fail for a specific symbol)
        active_df['ltp'] = active_df['symbol'].map(live_prices).fillna(active_df['wacc'])

        # 4. Math Calculations (Current Value, P/L, Weight, Breakeven)
        active_df['current_val'] = active_df['net_qty'] * active_df['ltp']
        active_df['pl_amt'] = active_df['current_val'] - active_df['total_cost']
        active_df['pl_pct'] = np.where(active_df['total_cost'] > 0, (active_df['pl_amt'] / active_df['total_cost']) * 100, 0)
        
        total_val = active_df['current_val'].sum()
        active_df['weight'] = np.where(total_val > 0, (active_df['current_val'] / total_val) * 100, 0)
        active_df['breakeven'] = (active_df['wacc'] * 1.005) + (25 / active_df['net_qty'])

        # 5. Build JSON Response
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
            "summary": {
                "total_invested": round(float(active_df['total_cost'].sum()), 2),
                "total_current_value": round(float(total_val), 2),
                "total_unrealized_pl": round(float(active_df['pl_amt'].sum()), 2),
                "total_pl_pct": round(float((active_df['pl_amt'].sum() / active_df['total_cost'].sum()) * 100) if active_df['total_cost'].sum() > 0 else 0, 2)
            },
            "data": data_list
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
