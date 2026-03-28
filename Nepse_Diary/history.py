from fastapi import APIRouter, Depends
from sqlalchemy import text
from datetime import date, timedelta
import pandas as pd
# Import your get_db_engine or session here

router = APIRouter()

@router.get("/trade_history")
def get_trade_history():
    engine = get_db_engine() # Use your existing DB connection logic
    
    with engine.connect() as conn:
        # 1. Fetch Data
        port_df = pd.read_sql("SELECT * FROM portfolio ORDER BY date ASC, transaction_type DESC", conn)
        cache_df = pd.read_sql("SELECT symbol, ltp FROM cache", conn)
        ltp_dict = dict(zip(cache_df['symbol'].str.upper(), pd.to_numeric(cache_df['ltp'])))

    # 2. FIFO Engine (Your Streamlit logic ported)
    inventory = {}
    realized_records = []
    
    for _, row in port_df.iterrows():
        sym = row['symbol'].upper()
        if sym not in inventory: inventory[sym] = []
        
        if row['transaction_type'].upper() == 'BUY':
            inventory[sym].append({
                'qty': row['qty'], 'buy_rate': row['price'],
                'buy_date': row['date'], 'unit_cost': (row['total_invested'] / row['qty'])
            })
        elif row['transaction_type'].upper() == 'SELL':
            rem = row['qty']
            rec_per_unit = row['total_received'] / row['qty']
            while rem > 0 and inventory.get(sym):
                lot = inventory[sym][0]
                take = min(lot['qty'], rem)
                realized_records.append({
                    'symbol': sym, 'qty': take, 'buy_date': lot['buy_date'], 'sell_date': row['date'],
                    'buy_rate': lot['buy_rate'], 'sell_rate': row['price'],
                    'pnl': take * (rec_per_unit - lot['unit_cost'])
                })
                lot['qty'] -= take
                rem -= take
                if lot['qty'] <= 0: inventory[sym].pop(0)

    # 3. Format Response
    # (Extract Unrealized, Settlements, and Ledger into a single JSON object)
    return {
        "realized": realized_records,
        "ledger": port_df.to_dict(orient='records'),
        "unsettled": port_df[port_df['date'] > (date.today() - timedelta(days=3))].to_dict(orient='records')
    }
