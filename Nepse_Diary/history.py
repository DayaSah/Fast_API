import pandas as pd
import numpy as np
from datetime import date, timedelta, datetime
import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from database import get_db_engine

# Import the cache from your main app or active_portfolio file
# (Assuming they are in the same FastAPI process)
try:
    from active_portfolio import LOCAL_MARKET_CACHE
except ImportError:
    # Fallback if imported differently
    LOCAL_MARKET_CACHE = {"data": {}, "last_updated": None, "status": "Initializing"}

router = APIRouter()

def calculate_detailed_fifo(df, ltp_dict):
    """
    Advanced FIFO Engine: 
    Calculates Realized Trades (Closed) and Unrealized Lots (Open).
    """
    inventory = {}  # Active holding queues per symbol
    realized_records = []
    
    # Sort chronologically for FIFO
    df = df.sort_values(by=['date', 'transaction_type'], ascending=[True, False])

    for _, row in df.iterrows():
        sym = row['symbol'].upper()
        if sym not in inventory:
            inventory[sym] = []
        
        qty = abs(int(row['qty']))
        price = float(row['price'])
        # Handle cases where total_invested/received might be missing
        total_inv = float(row.get('total_invested', qty * price))
        total_rec = float(row.get('total_received', qty * price))

        if row['transaction_type'].upper() == 'BUY':
            unit_cost = total_inv / qty if qty > 0 else 0
            inventory[sym].append({
                'qty': qty,
                'buy_rate': price,
                'unit_cost': unit_cost,
                'buy_date': row['date'],
                'buy_remark': row.get('remarks', '-')
            })
            
        elif row['transaction_type'].upper() == 'SELL':
            rem = qty
            rec_per_unit = total_rec / qty if qty > 0 else 0
            
            while rem > 0 and inventory[sym]:
                buy_lot = inventory[sym][0]
                
                if buy_lot['qty'] <= rem:
                    matched_qty = buy_lot['qty']
                    rem -= matched_qty
                    inventory[sym].pop(0)
                else:
                    matched_qty = rem
                    buy_lot['qty'] -= rem
                    rem = 0
                
                # Math for this specific matched lot
                invested = matched_qty * buy_lot['unit_cost']
                received = matched_qty * rec_per_unit
                net_pl = received - invested
                
                realized_records.append({
                    'symbol': sym,
                    'qty': matched_qty,
                    'buy_date': buy_lot['buy_date'].strftime('%Y-%m-%d'),
                    'sell_date': row['date'].strftime('%Y-%m-%d'),
                    'buy_rate': round(buy_lot['buy_rate'], 2),
                    'sell_rate': round(price, 2),
                    'net_pl': round(net_pl, 2),
                    'roi_pct': round((net_pl / invested * 100), 2) if invested > 0 else 0,
                    'remarks': f"B: {buy_lot['buy_remark']} | S: {row.get('remarks', '-')}"
                })

    # Remaining lots are Unrealized
    unrealized_records = []
    for sym, lots in inventory.items():
        for lot in lots:
            if lot['qty'] > 0:
                ltp = ltp_dict.get(sym, lot['unit_cost'])
                invested = lot['qty'] * lot['unit_cost']
                current_val = lot['qty'] * ltp
                net_pl = current_val - invested
                
                unrealized_records.append({
                    'symbol': sym,
                    'qty': lot['qty'],
                    'buy_date': lot['buy_date'].strftime('%Y-%m-%d'),
                    'buy_rate': round(lot['buy_rate'], 2),
                    'ltp': round(ltp, 2),
                    'net_pl': round(net_pl, 2),
                    'roi_pct': round((net_pl / invested * 100), 2) if invested > 0 else 0,
                    'remark': lot['buy_remark']
                })

    return realized_records, unrealized_records

@router.get("/trade_history")
def get_trade_history(engine = Depends(get_db_engine)):
    try:
        with engine.connect() as conn:
            query = text("SELECT * FROM public.portfolio")
            df = pd.read_sql(query, con=conn)

        if df.empty:
            return {"status": "success", "message": "No trades found.", "data": {}}

        # Standardize Columns
        df.columns = [c.lower() for c in df.columns]
        df['date'] = pd.to_datetime(df['date'])
        
        # 1. T+2 Settlement Calculation
        nepal_tz = pytz.timezone('Asia/Kathmandu')
        today = datetime.now(nepal_tz).date()
        cutoff_date = pd.to_datetime(today - timedelta(days=3))
        
        df['settled'] = df['date'] <= cutoff_date
        
        unsettled_list = df[~df['settled']].copy()
        unsettled_data = []
        for _, row in unsettled_list.iterrows():
            unsettled_data.append({
                "date": row['date'].strftime('%Y-%m-%d'),
                "symbol": row['symbol'],
                "type": row['transaction_type'],
                "qty": int(row['qty']),
                "amount": round(float(row.get('total_invested', 0) if row['transaction_type'] == 'BUY' else row.get('total_received', 0)), 2)
            })

        # 2. FIFO Processing
        ltp_dict = LOCAL_MARKET_CACHE.get("data", {})
        realized, unrealized = calculate_detailed_fifo(df, ltp_dict)

        # 3. Summary Stats
        total_realized_pl = sum(r['net_pl'] for r in realized)
        win_trades = [r for r in realized if r['net_pl'] > 0]
        win_rate = (len(win_trades) / len(realized) * 100) if realized else 0

        return {
            "status": "success",
            "summary": {
                "total_realized_pl": round(total_realized_pl, 2),
                "win_rate": f"{round(win_rate, 2)}%",
                "total_closed_lots": len(realized),
                "total_open_lots": len(unrealized),
                "pending_settlements": len(unsettled_data)
            },
            "realized_history": realized,
            "unrealized_lots": unrealized,
            "unsettled_trades": unsettled_data
        }

    except Exception as e:
        print(f"🚨 History API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
