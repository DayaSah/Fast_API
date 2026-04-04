import pandas as pd
import numpy as np
import datetime
import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from database import get_db_engine

router = APIRouter()

# --- NEPSE FEE & TAX CALCULATOR (THE RECOGNIZED ACCURACY) ---
def calculate_net_sell_receivable(ltp, qty, wacc):
    """
    Calculates exactly how much cash you get after selling at LTP.
    Includes Broker Commission, SEBON fee, DP fee, and 7.5% CGT on profit.
    """
    gross_amount = ltp * qty
    
    # 1. Broker Commission (Standard NEPSE Tiers)
    if gross_amount <= 50000: comm_rate = 0.0040
    elif gross_amount <= 500000: comm_rate = 0.0037
    elif gross_amount <= 2000000: comm_rate = 0.0034
    elif gross_amount <= 10000000: comm_rate = 0.0030
    else: comm_rate = 0.0027
        
    broker_comm = gross_amount * comm_rate
    sebon_fee = gross_amount * 0.00015
    dp_fee = 25
    
    # Total Selling Cost before Tax
    selling_costs = broker_comm + sebon_fee + dp_fee
    net_selling_price = gross_amount - selling_costs
    
    # 2. Capital Gains Tax (CGT) - 7.5% for Individuals
    total_purchase_cost = wacc * qty
    profit = net_selling_price - total_purchase_cost
    
    cgt_tax = max(0, profit * 0.075) # Only tax if there is a profit
    final_receivable = net_selling_price - cgt_tax
    
    return final_receivable, (selling_costs + cgt_tax)

# --- FINANCIAL LOGIC (FIFO WACC) ---
def calculate_fifo_wacc(df):
    """NEPSE-Standard FIFO Calculation with clean data handling."""
    active_holdings = []
    if df.empty: return pd.DataFrame()
    
    # Standardize column names to lowercase
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
        # 1. Fetch data from DB tables (Portfolio & GitHub-updated Cache)
        with engine.connect() as conn:
            port_query = text("SELECT symbol, qty, net_amount, transaction_type, date FROM public.portfolio")
            cache_query = text("SELECT symbol, ltp FROM public.cache")
            
            port_df = pd.read_sql(port_query, con=conn)
            cache_df = pd.read_sql(cache_query, con=conn)
            
        if port_df.empty:
            return {"status": "success", "data": [], "message": "Portfolio ledger is empty."}
        
        # 2. Process FIFO logic to get current holdings
        active_df = calculate_fifo_wacc(port_df)
        
        # 3. Merge Live Prices from the Cache table
        if not cache_df.empty:
            cache_df['symbol'] = cache_df['symbol'].str.strip().str.upper()
            cache_dict = dict(zip(cache_df['symbol'], cache_df['ltp']))
            active_df['ltp'] = active_df['symbol'].map(cache_dict).fillna(active_df['wacc'])
        else:
            active_df['ltp'] = active_df['wacc']

        # 4. Detailed Calculation Loop
        results = []
        total_inv = 0
        total_receivable = 0

        for _, row in active_df.iterrows():
            # Apply our Advanced Tax/Fee Function
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
                "exit_charges_inclusive_tax": round(float(total_exit_fees), 2), 
                "real_pl_amt": round(float(real_pl), 2), 
                "real_pl_pct": round(float(real_pl_pct), 2),
                "weight": 0 # Placeholder for post-loop calculation
            })

        # 5. Finalize Weights & Metadata
        for item in results:
            if total_receivable > 0:
                item['weight'] = round((item['receivable_val'] / total_receivable) * 100, 1)

        nepal_tz = pytz.timezone('Asia/Kathmandu')
        return {
            "status": "success",
            "metadata": {
                "market_data_source": "GitHub-DB Cache",
                "server_time": datetime.datetime.now(nepal_tz).strftime("%H:%M:%S")
            },
            "summary": {
                "total_invested": round(total_inv, 2),
                "net_liquid_value": round(total_receivable, 2),
                "actual_net_profit": round(total_receivable - total_inv, 2),
                "overall_net_gain_pct": round(((total_receivable - total_inv) / total_inv * 100) if total_inv > 0 else 0, 2)
            },
            "data": results
        }

    except Exception as e:
        print(f"🚨 [DB-API ERROR]: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database or Calculation Error: {str(e)}")
