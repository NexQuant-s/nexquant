"""Télécharge l'historique H1 MT5 (lecture seule) dans data/<SYMBOLE>.csv + data/meta.json (spread, point).
Usage : python fetch_data.py   (terminal MT5 ouvert). Les barres sont en HEURE SERVEUR (UTC+2/+3)."""
import json
import os
import time

import MetaTrader5 as mt5
import pandas as pd

SYMS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY",
        "XAUUSD", "XAGUSD", "XPTUSD", "XCUUSD", "XTIUSD", "XBRUSD", "XNGUSD",
        "US500", "NAS100", "US30", "JPN225", "UK100", "EUSTX50", "FRA40", "AUS200", "HK50", "BTCUSD", "ETHUSD"]
os.makedirs("data", exist_ok=True)
assert mt5.initialize(), mt5.last_error()
meta = {}
for s in SYMS:
    mt5.symbol_select(s, True)
    r = None
    for _ in range(10):
        time.sleep(3)
        r = mt5.copy_rates_from_pos(s, mt5.TIMEFRAME_H1, 0, 20000)
        if r is not None and len(r) > 3000:
            break
    i = mt5.symbol_info(s)
    if i is None or r is None or len(r) < 3000:
        print(s, "indisponible")
        continue
    df = pd.DataFrame(r)
    df["t"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("t")[["open", "high", "low", "close", "tick_volume"]].to_csv(f"data/{s}.csv")
    meta[s] = dict(spread=i.spread * i.point, point=i.point, bars=len(df))
json.dump(meta, open("data/meta.json", "w"))
mt5.shutdown()
