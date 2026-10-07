"""Bougies MT5 en heure serveur : les logiques horaires doivent utiliser l'heure UTC réelle."""

import numpy as np
import pandas as pd

from superbot.indicators.technical_indicators import TechnicalIndicators
from superbot.strategy.knowledge_base import calculate_asian_range, utc_bar_times

OFFSET = 3 * 3600  # serveur Fusion Markets en UTC+3


def _server_time_candles(n=200):
    # Index en heure SERVEUR (étiquetée UTC), comme MT5Client.fetch_candles
    index = pd.date_range("2026-10-06 00:00", periods=n, freq="15min", tz="UTC")
    close = 1.10 + np.cumsum(np.random.default_rng(0).normal(0, 0.0005, n))
    df = pd.DataFrame({"open": close, "high": close + 0.0004, "low": close - 0.0004,
                       "close": close, "volume": 100.0}, index=index)
    df["server_utc_offset_s"] = OFFSET
    return df


def test_utc_bar_times_subtracts_server_offset():
    df = _server_time_candles(8)
    assert utc_bar_times(df)[0] == pd.Timestamp("2026-10-05 21:00", tz="UTC")


def test_without_offset_column_index_is_unchanged():
    df = _server_time_candles(8).drop(columns=["server_utc_offset_s"])
    assert utc_bar_times(df)[0] == df.index[0]


def test_offset_column_survives_indicators():
    out = TechnicalIndicators({}).calculate_all_indicators(_server_time_candles())
    assert "server_utc_offset_s" in out.columns
    assert utc_bar_times(out)[-1] == out.index[-1] - pd.Timedelta(hours=3)


def test_asian_range_uses_real_utc_session():
    df = _server_time_candles(200)
    # Barre serveur 09:00 = 06:00 UTC : dans la session asiatique UTC (00h-07h),
    # mais hors de la fenêtre 00h-07h en heure serveur utilisée par l'ancien code.
    df.loc[pd.Timestamp("2026-10-07 09:00", tz="UTC"), "high"] = 9.0
    high, _, _ = calculate_asian_range(df.loc[:pd.Timestamp("2026-10-07 12:00", tz="UTC")])
    assert high == 9.0
