"""Banc d'essai réaliste de stratégies (H1/H4/D1), sans optimisation de paramètres.

Règles : signal sur bougie clôturée, entrée à l'ouverture suivante, spread réel x1,5 (+0,5 spread de glissement
sur les sorties par stop), stop initial >= 1 ATR (donc R borné), stop vérifié avant l'objectif (pessimiste).
"""
import json
import os
import sys
import numpy as np
import pandas as pd

H = os.path.dirname(os.path.abspath(__file__))
META = json.load(open(f"{H}/data/meta.json"))
SYMS = list(META)
SPLIT = pd.Timestamp("2025-03-01")
HOURS = {"1h": 1, "4h": 4, "1d": 24}


# ── données et indicateurs ─────────────────────────────────────────────────────
def load(sym, tf):
    df = pd.read_csv(f"{H}/data/{sym}.csv", index_col=0, parse_dates=True)
    df = df[~df.index.duplicated()].sort_index()
    if tf != "1h":
        rule = {"4h": "4h", "1d": "1D"}[tf]
        df = df.resample(rule, origin="start_day").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum"}).dropna()
    return df


def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def sma(s, n): return s.rolling(n).mean()


def atr_f(df, n=14):
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rsi_f(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def adx_f(df, n=14):
    up, dn = df["high"].diff(), -df["low"].diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = atr_f(df, n)
    pdi = 100 * pd.Series(pdm, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * pd.Series(mdm, df.index).ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), pdi, mdi


def supertrend_dir(df, atr, mult=3.0):
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    a = atr.values; n = len(c); hl2 = (h + l) / 2
    ub, lb = hl2 + mult * a, hl2 - mult * a
    fub, flb, d = ub.copy(), lb.copy(), np.ones(n)
    for i in range(1, n):
        if np.isnan(a[i]): d[i] = d[i - 1]; continue
        fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
        flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
        if d[i - 1] == 1 and c[i] < flb[i]: d[i] = -1
        elif d[i - 1] == -1 and c[i] > fub[i]: d[i] = 1
        else: d[i] = d[i - 1]
    return pd.Series(d, df.index)


def cross_up(a, b): return (a > b) & (a.shift() <= b.shift())
def cross_dn(a, b): return (a < b) & (a.shift() >= b.shift())


def utc_hour(idx):
    approx = pd.DatetimeIndex(idx - pd.Timedelta(hours=2.5)).tz_localize("UTC").tz_convert("America/New_York")
    off = np.where(np.array([x.dst() != pd.Timedelta(0) for x in approx]), 3, 2)
    return (idx - pd.to_timedelta(off, unit="h")).hour


# ── simulateur ────────────────────────────────────────────────────────────────
def simulate(df, sl, ss, atr, spread, p, xl=None, xs=None):
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    a = atr.values; n = len(df); idx = df.index
    sig_l = sl.fillna(False).values; sig_s = ss.fillna(False).values
    xl_ = xl.fillna(False).values if xl is not None else None
    xs_ = xs.fillna(False).values if xs is not None else None
    sl_m, trail_m, tp_m, max_bars = p["sl"], p.get("trail", 0), p.get("tp", 0), p["max_bars"]
    base_cost = 1.5 * spread; slip = 0.5 * spread
    out = []; t = 0
    while t < n - 2:
        d = 1 if sig_l[t] and not sig_s[t] else (-1 if sig_s[t] and not sig_l[t] else 0)
        if d == 0 or not (a[t] > 0): t += 1; continue
        entry = o[t + 1]; sd = sl_m * a[t]; stop = entry - d * sd
        tp = entry + d * tp_m * a[t] if tp_m else None
        ext = entry; exit_p = None; exit_j = None; stopped = False
        for j in range(t + 1, n):
            if d == 1:
                if o[j] <= stop: exit_p, stopped = o[j], True
                elif l[j] <= stop: exit_p, stopped = stop, True
                elif tp is not None and h[j] >= tp: exit_p = tp
            else:
                if o[j] >= stop: exit_p, stopped = o[j], True
                elif h[j] >= stop: exit_p, stopped = stop, True
                elif tp is not None and l[j] <= tp: exit_p = tp
            if exit_p is not None: exit_j = j; break
            if trail_m:
                if d == 1: ext = max(ext, h[j]); stop = max(stop, ext - trail_m * a[t])
                else: ext = min(ext, l[j]); stop = min(stop, ext + trail_m * a[t])
            if j - t >= max_bars: exit_p, exit_j = c[j], j; break
            xsig = xl_ if d == 1 else xs_
            if xsig is not None and xsig[j] and j + 1 < n: exit_p, exit_j = o[j + 1], j + 1; break
        if exit_p is None: break
        cost = base_cost + (slip if stopped else 0.0)
        out.append((idx[t + 1], d * (exit_p - entry) / sd - cost / sd, exit_j - t))
        t = max(exit_j, t + 1)
    return out


# ── stratégies : (long, short, exit_long, exit_short, params) ─────────────────────
def mb(base_hours, tf): return max(5, int(base_hours / HOURS[tf]))


def s_donch(n):
    def f(df, tf):
        hh = df["high"].rolling(n).max().shift(); ll = df["low"].rolling(n).min().shift()
        return df["close"] > hh, df["close"] < ll, None, None, dict(sl=2, trail=3, max_bars=mb(24 * 40, tf))
    return f


def s_ema_cross(df, tf):
    f, s = ema(df["close"], 20), ema(df["close"], 50)
    return cross_up(f, s), cross_dn(f, s), cross_dn(f, s), cross_up(f, s), dict(sl=2, trail=3, max_bars=mb(24 * 40, tf))


def s_pullback(df, tf):
    c, e20, e50, e200 = df["close"], ema(df["close"], 20), ema(df["close"], 50), ema(df["close"], 200)
    adx, _, _ = adx_f(df)
    up = (e50 > e200) & (c > e200) & (adx > 20); dn = (e50 < e200) & (c < e200) & (adx > 20)
    return up & (df["low"] <= e20) & (c > e20), dn & (df["high"] >= e20) & (c < e20), None, None, dict(sl=2, trail=2.5, max_bars=mb(24 * 20, tf))


def s_supertrend(df, tf):
    d = supertrend_dir(df, atr_f(df, 10), 3.0)
    return (d == 1) & (d.shift() == -1), (d == -1) & (d.shift() == 1), d == -1, d == 1, dict(sl=2, trail=0, max_bars=mb(24 * 40, tf))


def s_keltner(df, tf):
    m, a = ema(df["close"], 20), atr_f(df, 14)
    return df["close"] > m + 2 * a, df["close"] < m - 2 * a, None, None, dict(sl=2, trail=3, max_bars=mb(24 * 30, tf))


def s_squeeze(df, tf):
    c = df["close"]; m, sd = sma(c, 20), c.rolling(20).std(); w = (4 * sd) / m
    sq = w <= w.rolling(120).quantile(0.2)
    sqz = sq.shift().rolling(3).max() > 0
    return sqz & (c > m + 2 * sd), sqz & (c < m - 2 * sd), None, None, dict(sl=2, trail=3, max_bars=mb(24 * 30, tf))


def s_tsmom(L):
    def f(df, tf):
        r = df["close"].pct_change(L)
        return (r > 0) & (r.shift() <= 0), (r < 0) & (r.shift() >= 0), r < 0, r > 0, dict(sl=4, trail=0, max_bars=10 ** 6)
    return f


def s_rsi2(df, tf):
    c = df["close"]; r = rsi_f(c, 2); tr = sma(c, 200); s5 = sma(c, 5)
    return (r < 10) & (c > tr), (r > 90) & (c < tr), (r > 60) | (c > s5), (r < 40) | (c < s5), dict(sl=3, trail=0, max_bars=mb(24 * 3, tf))


def s_bb_revert(df, tf):
    c = df["close"]; m, sd = sma(c, 20), c.rolling(20).std(); adx, _, _ = adx_f(df)
    return (c < m - 2 * sd) & (adx < 22), (c > m + 2 * sd) & (adx < 22), c > m, c < m, dict(sl=2.5, trail=0, max_bars=mb(24 * 4, tf))


def s_rsi_range(df, tf):
    r = rsi_f(df["close"], 14); adx, _, _ = adx_f(df)
    return (r < 25) & (adx < 20), (r > 75) & (adx < 20), r > 50, r < 50, dict(sl=2.5, trail=0, max_bars=mb(24 * 4, tf))


def s_zscore(df, tf):
    c = df["close"]; z = (c - sma(c, 50)) / c.rolling(50).std(); adx, _, _ = adx_f(df)
    return (z < -2.5) & (adx < 25), (z > 2.5) & (adx < 25), z > 0, z < 0, dict(sl=2.5, trail=0, max_bars=mb(24 * 5, tf))


def s_nr7(df, tf):
    rg = df["high"] - df["low"]; nr = rg == rg.rolling(7).min()
    return nr.shift() & (df["close"] > df["high"].shift()), nr.shift() & (df["close"] < df["low"].shift()), None, None, dict(sl=2, trail=2.5, max_bars=mb(24 * 10, tf))


def s_london(df, tf):
    if tf != "1h": return None
    hr = utc_hour(df.index); day = df.index.normalize()
    asian = pd.Series(np.where((hr >= 0) & (hr < 7), 1, 0), df.index)
    hi = df["high"].where(asian == 1).groupby(day).transform("max"); lo = df["low"].where(asian == 1).groupby(day).transform("min")
    win = pd.Series((hr >= 7) & (hr < 11), df.index); a = atr_f(df)
    longs = win & (df["close"] > hi + 0.1 * a); shorts = win & (df["close"] < lo - 0.1 * a)
    longs &= (longs.groupby(day).cumsum() == 1)  # une seule entrée par jour et par sens
    shorts &= (shorts.groupby(day).cumsum() == 1)
    return longs, shorts, None, None, dict(sl=1.5, tp=3, trail=0, max_bars=10)


def s_volbreak(df, tf):
    if tf != "1h": return None
    day = df.index.normalize(); d = df.groupby(day).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"))
    prev = (d["h"] - d["l"]).shift(); dd = pd.DataFrame({"op": d["o"], "rg": prev}).reindex(day).set_index(df.index)
    up = dd["op"] + 0.6 * dd["rg"]; dn = dd["op"] - 0.6 * dd["rg"]
    hr = df.index.hour
    ok = pd.Series((hr >= 2) & (hr <= 18), df.index)
    return ok & (df["close"] > up), ok & (df["close"] < dn), None, None, dict(sl=1.5, tp=0, trail=2, max_bars=12)


STRATS = {
    "donch20": s_donch(20), "donch55": s_donch(55), "ema20_50": s_ema_cross, "pullback_ema": s_pullback,
    "supertrend": s_supertrend, "keltner_brk": s_keltner, "squeeze_brk": s_squeeze, "nr7_brk": s_nr7,
    "tsmom20": s_tsmom(20), "tsmom60": s_tsmom(60), "rsi2_connors": s_rsi2, "bb_revert": s_bb_revert,
    "rsi_range": s_rsi_range, "zscore_revert": s_zscore, "london_brk": s_london, "vol_brk": s_volbreak,
}
SKIP = {("tsmom20", "1h"), ("tsmom60", "1h"), ("tsmom20", "4h"), ("tsmom60", "4h")}


def run(name, tf, syms=None):
    rows = []
    for sym in syms or SYMS:
        df = load(sym, tf)
        res = STRATS[name](df, tf)
        if res is None: return None
        sl_, ss_, xl, xs, p = res
        for t, r, b in simulate(df, sl_, ss_, atr_f(df), META[sym]["spread"], p, xl, xs):
            rows.append((sym, t, r, b))
    return pd.DataFrame(rows, columns=["sym", "t", "R", "bars"])


def pf(r):
    l = -r[r < 0].sum()
    return float(r[r > 0].sum() / l) if l > 0 else float("inf")


def summarize(name, tf, d):
    r = d["R"]; tr, te = d[d.t < SPLIT], d[d.t >= SPLIT]
    cl = lambda x: x.clip(upper=6)
    per = d.groupby("sym")["R"].apply(lambda x: pf(cl(x)))
    cum = d.sort_values("t")["R"].cumsum(); dd = float((cum.cummax() - cum).max())
    days = max((d.t.max() - d.t.min()).days, 1) * 5 / 7
    return dict(strat=name, tf=tf, n=len(d), per_day=round(len(d) / days, 2), wr=round((r > 0).mean() * 100),
                expR=round(cl(r).mean(), 3), pf=round(pf(cl(r)), 2), pf_tr=round(pf(cl(tr.R)), 2), pf_te=round(pf(cl(te.R)), 2),
                sym_ok=f"{int((per > 1).sum())}/{len(per)}", dd_R=round(dd, 1), R_gt6=f"{(r > 6).mean() * 100:.1f}%")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8"); pd.set_option("display.width", 250)
    names = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(STRATS)
    tfs = sys.argv[2].split(",") if len(sys.argv) > 2 else ["1h", "4h", "1d"]
    rows = []; os.makedirs(f"{H}/out", exist_ok=True)
    for tf in tfs:
        for name in names:
            if (name, tf) in SKIP: continue
            try:
                d = run(name, tf)
            except Exception as e:
                print(f"ERREUR {name} {tf}: {type(e).__name__}: {e}", flush=True); continue
            if d is None or len(d) < 30: continue
            d.to_pickle(f"{H}/out/{name}_{tf}.pkl"); rows.append(summarize(name, tf, d)); print(rows[-1], flush=True)
    res = pd.DataFrame(rows)
    res["robuste"] = res[["pf_tr", "pf_te"]].min(axis=1)
    res = res.sort_values("robuste", ascending=False); res.to_csv(f"{H}/out/resultats_{'_'.join(tfs)}.csv", index=False)
    print(res.to_string(index=False))
