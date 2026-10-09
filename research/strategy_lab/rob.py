import sys, itertools, numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8"); pd.set_option("display.width", 220)
import lab
from lab import *

def pullback(pull=20, fast=50, slow=200, adx_min=20, sl=2.0, trail=2.5):
    def f(df, tf):
        c, ep, ef, es = df["close"], ema(df["close"], pull), ema(df["close"], fast), ema(df["close"], slow)
        adx, _, _ = adx_f(df)
        up = (ef > es) & (c > es) & (adx > adx_min); dn = (ef < es) & (c < es) & (adx > adx_min)
        return up & (df["low"] <= ep) & (c > ep), dn & (df["high"] >= ep) & (c < ep), None, None, dict(sl=sl, trail=trail, max_bars=mb(24 * 20, tf))
    return f

CLS = {"fx_maj": ["EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF","NZDUSD"], "fx_cross": ["EURGBP","EURJPY","GBPJPY","AUDJPY"],
       "metaux": ["XAUUSD","XAGUSD","XPTUSD","XCUUSD"], "energie": ["XTIUSD","XBRUSD","XNGUSD"],
       "indices": ["US500","NAS100","US30","JPN225","UK100","EUSTX50","FRA40","AUS200","HK50"], "crypto": ["BTCUSD","ETHUSD"]}
DATA = {s: load(s, "1d") for s in lab.SYMS}

def trades(fn):
    rows = []
    for s, df in DATA.items():
        sl_, ss_, xl, xs, p = fn(df, "1d")
        for t, r, b in simulate(df, sl_, ss_, atr_f(df), lab.META[s]["spread"], p, xl, xs): rows.append((s, t, r, b))
    return pd.DataFrame(rows, columns=["sym", "t", "R", "bars"])

def stats(d):
    c = d.R.clip(upper=6); tr, te = d[d.t < lab.SPLIT].R.clip(upper=6), d[d.t >= lab.SPLIT].R.clip(upper=6)
    return dict(n=len(d), expR=round(c.mean(), 3), pf=round(pf(c), 2), tr=round(pf(tr), 2), te=round(pf(te), 2))

base = trades(pullback()); print("BASE", stats(base))
print("\n== par classe d'actifs"); 
for k, v in CLS.items(): print(f"{k:9s}", stats(base[base.sym.isin(v)]))
print("\n== par tiers de période")
q = base.t.quantile([0, .333, .667, 1]).values
for i in range(3): print(f"tiers {i+1}", stats(base[(base.t >= q[i]) & (base.t <= q[i+1])]))
print("\n== sans les 5 % meilleurs trades:", stats(base[base.R <= base.R.quantile(.95)]))
print("\n== voisinage de paramètres (PF global / apprentissage / test)")
rows = []
for pull, sl, trail, adx_min in itertools.product((10, 20, 30), (1.5, 2.0, 3.0), (2.0, 2.5, 3.5), (15, 20, 25)):
    d = trades(pullback(pull=pull, sl=sl, trail=trail, adx_min=adx_min)); s = stats(d)
    rows.append(dict(pull=pull, sl=sl, trail=trail, adx=adx_min, **s))
g = pd.DataFrame(rows)
print(g.sort_values("pf", ascending=False).head(8).to_string(index=False))
print(f"\n{len(g)} variantes : PF médian {g.pf.median():.2f} | min {g.pf.min():.2f} | max {g.pf.max():.2f} | variantes PF>1 : {(g.pf>1).sum()}/{len(g)} | tr>1 ET te>1 : {((g.tr>1)&(g.te>1)).sum()}/{len(g)}")
for col in ("pull", "sl", "trail", "adx"): print(col, g.groupby(col).pf.median().round(2).to_dict())
