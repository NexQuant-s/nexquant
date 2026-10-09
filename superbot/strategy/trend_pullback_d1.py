"""
Pullback de tendance en D1 (« swing ») — stratégie pure, sans accès broker.

Validée en banc d'essai (09/10/2026, spread réel x1,5, entrée à l'ouverture suivante, 3 ans) :
- tendance : EMA50 > EMA200, clôture > EMA200, ADX(14) > 25 (miroir pour les ventes)
- déclencheur : la bougie D1 touche l'EMA20 puis clôture de nouveau du bon côté
- stop initial 2 ATR(14), stop suiveur 3 ATR depuis l'extrême, sortie sur délai à 20 bougies
Panier faisable sur 900 € : indices (US500, NAS100, US30, JPN225, UK100, EUSTX50, FRA40, AUS200) + ETHUSD.
Résultat du panier : PF 1,75 (apprentissage 1,97 / test 1,52), +0,28 R/trade, 44 trades/an, drawdown 3 % à 0,5 % de risque.
Voisinage de paramètres : 81/81 variantes rentables. Réserve : 77 % de signaux acheteurs, 2023-2026 haussier.
"""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SwingParams:
    pull: int = 20
    fast: int = 50
    slow: int = 200
    adx_min: float = 25.0
    sl_atr: float = 2.0
    trail_atr: float = 3.0
    max_bars: int = 20
    atr_len: int = 14


DEFAULT_PARAMS = SwingParams()
MIN_BARS = 260  # EMA200 + ADX stabilisés


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, dn = df["high"].diff(), -df["low"].diff()
    pdm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), df.index)
    mdm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), df.index)
    a = atr(df, n)
    pdi = 100 * pdm.ewm(alpha=1 / n, adjust=False).mean() / a
    mdi = 100 * mdm.ewm(alpha=1 / n, adjust=False).mean() / a
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def signals(df: pd.DataFrame, p: SwingParams = DEFAULT_PARAMS):
    """Séries booléennes (achat, vente) sur chaque bougie D1 CLÔTURÉE du DataFrame."""
    c = df["close"]
    e_pull, e_fast, e_slow = _ema(c, p.pull), _ema(c, p.fast), _ema(c, p.slow)
    strength = adx(df, p.atr_len) > p.adx_min
    up = (e_fast > e_slow) & (c > e_slow) & strength
    dn = (e_fast < e_slow) & (c < e_slow) & strength
    return up & (df["low"] <= e_pull) & (c > e_pull), dn & (df["high"] >= e_pull) & (c < e_pull)


def evaluate(df: pd.DataFrame, p: SwingParams = DEFAULT_PARAMS) -> Optional[dict]:
    """Signal sur la dernière bougie clôturée de `df` : {'side', 'atr', 'close'} ou None."""
    if df is None or len(df) < MIN_BARS:
        return None
    long_s, short_s = signals(df, p)
    a = float(atr(df, p.atr_len).iloc[-1])
    if not (a > 0):
        return None
    is_long, is_short = bool(long_s.iloc[-1]), bool(short_s.iloc[-1])
    if is_long == is_short:  # aucun signal, ou signaux contradictoires
        return None
    return {"side": "LONG" if is_long else "SHORT", "atr": a, "close": float(df["close"].iloc[-1])}


def trailing_stop(side: str, entry_price: float, bars_since_entry: pd.DataFrame, atr_entry: float,
                  current_sl: float, p: SwingParams = DEFAULT_PARAMS) -> float:
    """Nouveau stop suiveur après les bougies clôturées depuis l'entrée (ne recule jamais)."""
    if bars_since_entry is None or len(bars_since_entry) == 0:
        return current_sl
    if side == "LONG":
        ext = max(entry_price, float(bars_since_entry["high"].max()))
        return max(current_sl, ext - p.trail_atr * atr_entry)
    ext = min(entry_price, float(bars_since_entry["low"].min()))
    return min(current_sl, ext + p.trail_atr * atr_entry)
