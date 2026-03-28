from fastapi import APIRouter, HTTPException
import pandas as pd
from sqlalchemy import text
from datetime import date, timedelta
from database import get_db_engine

router = APIRouter()

@router.get("/trade_history", tags=["Analytics"])
def get_trade_history():
    engine = get_db_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="DB Connection Failed")

    try:
        with engine.connect() as conn:
            # 1. Fetch Raw Data
            port_df = pd.read_sql("SELECT * FROM portfolio ORDER BY date ASC, transaction_type DESC", conn)
            cache_df = pd.read_sql("SELECT symbol, ltp FROM cache", conn)
            ltp_dict = dict(zip(cache_df['symbol'].str.upper(), pd.to_numeric(cache_df['ltp'])))

        if port_df.empty:
            return {"realized": [], "unsettled": [], "ledger": []}

        # 2. FIFO Engine Logic
        inventory = {}
        realized_records = []
        
        for _, row in port_df.iterrows():
            sym = row['symbol'].upper()
            if sym not in inventory: inventory[sym] = []
            
            if row['transaction_type'].upper() == 'BUY':
                inventory[sym].append({
                    'qty': row['qty'], 'buy_rate': row['price'], 'buy_date': row['date'],
                    'unit_cost': (row['total_invested'] / row['qty']) if row['qty'] > 0 else 0
                })
            elif row['transaction_type'].upper() == 'SELL':
                rem = row['qty']
                rec_per_unit = row['total_received'] / row['qty'] if row['qty'] > 0 else 0
                while rem > 0 and inventory.get(sym):
                    lot = inventory[sym][0]
                    take = min(lot['qty'], rem)
                    realized_records.append({
                        'symbol': sym, 'qty': take, 'buy_date': str(lot['buy_date']), 
                        'sell_date': str(row['date']), 'buy_rate': lot['buy_rate'], 
                        'sell_rate': row['price'], 'pnl': take * (rec_per_unit - lot['unit_cost'])
                    })
                    lot['qty'] -= take
                    rem -= take
                    if lot['qty'] <= 0: inventory[sym].pop(0)

        # 3. Settlement Calculation (T+2)
        cutoff_date = date.today() - timedelta(days=3)
        port_df['is_unsettled'] = pd.to_datetime(port_df['date']).dt.date > cutoff_date
        unsettled = port_df[port_df['is_unsettled'] == True]

        return {
            "realized": realized_records,
            "unsettled": unsettled.to_dict(orient='records'),
            "ledger": port_df.to_dict(orient='records')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
