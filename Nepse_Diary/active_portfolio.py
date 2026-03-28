from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
import pandas as pd
import numpy as np

# We assume you have a database.py file or similar that provides a database session
# from database import get_db

router = APIRouter()

def calculate_fifo_wacc(df):
    """
    NEPSE-Standard FIFO Calculation.
    Handles partial sells correctly and accounts for fees via net_amount.
    """
    active_holdings = []
    
    if df.empty:
        return pd.DataFrame(active_holdings)

    # Ensure date is datetime for sorting
    df['date'] = pd.to_datetime(df['date'])
    
    for symbol in df['symbol'].unique():
        symbol_df = df[df['symbol'] == symbol].sort_values('date')
        inventory = []  # List of buy lots
        
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
                        inventory.pop(0)  # Oldest lot fully sold
                    else:
                        # Deduct from oldest lot partially
                        unit_cost = inventory[0]['total_cost'] / inventory[0]['qty']
                        inventory[0]['qty'] -= rem
                        inventory[0]['total_cost'] -= (unit_cost * rem)
                        rem = 0
        
        if inventory:
            t_qty = sum(i['qty'] for i in inventory)
            t_cost = sum(i['total_cost'] for i in inventory)
            if t_qty > 0:
                active_holdings.append({
                    'symbol': symbol, 
                    'net_qty': t_qty, 
                    'wacc': t_cost / t_qty, 
                    'total_cost': t_cost
                })
            
    return pd.DataFrame(active_holdings)


@router.get("/active_portfolio")
def get_active_portfolio(engine): # We pass engine here or use dependency injection like: db: Session = Depends(get_db)
    """
    Returns the fully calculated active portfolio with live LTP and P/L metrics.
    """
    try:
        with engine.connect() as conn:
            # 1. Fetch data from NeonDb
            port_df = pd.read_sql(text("SELECT symbol, qty, net_amount, transaction_type, date FROM public.portfolio"), con=conn)
            cache_df = pd.read_sql(text("SELECT symbol, ltp FROM public.cache"), con=conn)
            
        # Standardize column names
        port_df.columns = [c.lower() for c in port_df.columns]
        cache_df.columns = [c.lower() for c in cache_df.columns]

        if port_df.empty:
             return {"status": "success", "data": []}

        # 2. Perform NEPSE-Standard FIFO Calculation
        active_df = calculate_fifo_wacc(port_df)
        
        if active_df.empty:
             return {"status": "success", "data": []}

        # 3. Integrate Live Prices (LTP)
        if not cache_df.empty:
            active_df = pd.merge(active_df, cache_df[['symbol', 'ltp']], on='symbol', how='left')
            # If LTP is missing, fall back to WACC
            active_df['ltp'] = pd.to_numeric(active_df['ltp']).fillna(active_df['wacc'])
        else:
            active_df['ltp'] = active_df['wacc']

        # 4. Financial Metrics Calculation
        active_df['current_val'] = active_df['net_qty'] * active_df['ltp']
        active_df['pl_amt'] = active_df['current_val'] - active_df['total_cost']
        
        # Handle division by zero for pl_pct
        active_df['pl_pct'] = np.where(
            active_df['total_cost'] > 0, 
            (active_df['pl_amt'] / active_df['total_cost']) * 100, 
            0
        )
        
        # Calculate Weightage
        total_portfolio_value = active_df['current_val'].sum()
        active_df['weight'] = np.where(
            total_portfolio_value > 0,
            (active_df['current_val'] / total_portfolio_value) * 100,
            0
        )
        
        # Calculate Breakeven (WACC + NEPSE broker fee approximation + sebon/dp)
        # Using the exact logic from your Streamlit code
        active_df['breakeven'] = (active_df['wacc'] * 1.005) + (25 / active_df['net_qty'])

        # 5. Format the final output for JSON serialization
        # Convert DataFrame to a list of dictionaries, rounding floats for clean API responses
        active_portfolio = []
        for _, row in active_df.iterrows():
            active_portfolio.append({
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
            
        # Sort alphabetically by symbol
        active_portfolio = sorted(active_portfolio, key=lambda x: x['symbol'])

        # Return the payload
        return {
            "status": "success", 
            "summary": {
                "total_invested": round(float(active_df['total_cost'].sum()), 2),
                "total_current_value": round(float(total_portfolio_value), 2),
                "total_unrealized_pl": round(float(active_df['pl_amt'].sum()), 2),
                "total_pl_pct": round(float((active_df['pl_amt'].sum() / active_df['total_cost'].sum()) * 100) if active_df['total_cost'].sum() > 0 else 0, 2)
            },
            "data": active_portfolio
        }

    except Exception as e:
        print(f"Error calculating active portfolio: {e}")
        raise HTTPException(status_code=500, detail=str(e))
