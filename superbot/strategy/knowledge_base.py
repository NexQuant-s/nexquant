"""
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╩
"""
import pandas as pd
import numpy as np
from typing import Tuple, Dict
import logging

log = logging.getLogger("strategy.knowledge_base")


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calcule l'Average True Range (ATR).

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        period: Période pour le calcul de l'ATR (défaut: 14)

    Returns:
        Série contenant les valeurs de l'ATR
    """
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr


def calculate_ema(data: pd.Series, period: int) -> pd.Series:
    """
    Calcule la Moyenne Mobile Exponentielle (EMA).

    Args:
        data: Série de données (généralement les prix de clôture)
        period: Période pour le calcul de l'EMA

    Returns:
        Série contenant les valeurs de l'EMA
    """
    return data.ewm(span=period, adjust=False).mean()


def calculate_sma(data: pd.Series, period: int) -> pd.Series:
    """
    Calcule la Moyenne Mobile Simple (SMA).

    Args:
        data: Série de données
        period: Période pour le calcul de la SMA

    Returns:
        Série contenant les valeurs de la SMA
    """
    return data.rolling(window=period).mean()


def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calcule l'Indice de Force Relative (RSI).

    Args:
        close: Série des prix de clôture
        period: Période pour le calcul du RSI (défaut: 14)

    Returns:
        Série contenant les valeurs du RSI (0-100)
    """
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    loss = loss.replace(0, 1e-10)
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calculate_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calcule le Moving Average Convergence Divergence (MACD).

    Args:
        close: Série des prix de clôture
        fast: Période de la moyenne rapide (défaut: 12)
        slow: Période de la moyenne lente (défaut: 26)
        signal: Période de la ligne de signal (défaut: 9)

    Returns:
        Tuple de (MACD line, Signal line, Histogram)
    """
    ema_fast = calculate_ema(close, fast)
    ema_slow = calculate_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Calcule l'Average Directional Index (ADX).

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        period: Période pour le calcul de l'ADX (défaut: 14)

    Returns:
        Série contenant les valeurs de l'ADX
    """
    # Calcul du True Range
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()

    # Calcul du Directional Movement
    dm_plus = high - high.shift()
    dm_minus = low.shift() - low
    dm_plus = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0)
    dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0)

    # Calcul du Directional Indicators
    di_plus = 100 * (dm_plus.rolling(window=period).mean() / atr)
    di_minus = 100 * (dm_minus.rolling(window=period).mean() / atr)

    # Calcul du DX et de l'ADX
    dx = 100 * abs(di_plus - di_minus) / (di_plus + di_minus)
    adx = dx.rolling(window=period).mean()
    return adx


def calculate_supertrend(high: pd.Series, low: pd.Series, close: pd.Series,
                        atr_period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    """
    Calcule l'indicateur Supertrend.

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        atr_period: Période pour le calcul de l'ATR (défaut: 10)
        multiplier: Multiplicateur pour l'ATR (défaut: 3.0)

    Returns:
        Tuple de (Supertrend line, Trend direction) où Trend direction est 1 pour haussier, -1 pour baissier
    """
    if len(close) < atr_period + 1:
        return pd.Series(np.nan, index=close.index), pd.Series(np.nan, index=close.index)
        
    atr = calculate_atr(high, low, close, atr_period)
    hl2 = (high + low) / 2
    # Boucle sur des tableaux NumPy : même algorithme qu'avant, mais sans les
    # affectations Series.iloc[i] (très lentes, appelées à chaque cycle et symbole).
    upper = (hl2 + (multiplier * atr)).to_numpy(dtype=float, copy=True)
    lower = (hl2 - (multiplier * atr)).to_numpy(dtype=float, copy=True)
    c = close.to_numpy(dtype=float)
    n = len(c)
    st = np.empty(n, dtype=float)
    tr = np.empty(n, dtype=int)
    st[0] = upper[0]
    tr[0] = 1

    for i in range(1, n):
        if c[i] <= upper[i - 1]:
            upper[i] = min(upper[i], upper[i - 1])
        if c[i] >= lower[i - 1]:
            lower[i] = max(lower[i], lower[i - 1])
        if c[i] <= st[i - 1]:
            tr[i] = -1
            st[i] = upper[i]
        else:
            tr[i] = 1
            st[i] = lower[i]

    return pd.Series(st, index=close.index), pd.Series(tr, index=close.index)


def calculate_bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    Calcule les Bandes de Bollinger.

    Args:
        close: Série des prix de clôture
        period: Période pour le calcul de la moyenne mobile (défaut: 20)
        std_dev: Nombre d'écarts-types pour les bandes (défaut: 2.0)

    Returns:
        Tuple de (Upper band, Middle band (SMA), Lower band)
    """
    sma = calculate_sma(close, period)
    std = close.rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return upper_band, sma, lower_band


def calculate_ichimoku(high: pd.Series, low: pd.Series, close: pd.Series,
                      tenkan: int = 9, kijun: int = 26, senkou_span_b: int = 52,
                      displacement: int = 26) -> Dict[str, pd.Series]:
    """
    Calcule l'indicateur Ichimoku Cloud.

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        tenkan: Période pour Tenkan-sen (défaut: 9)
        kijun: Période pour Kijun-sen (défaut: 26)
        senkou_span_b: Période pour Senkou Span B (défaut: 52)
        displacement: Décalage pour les nuages (défaut: 26)

    Returns:
        Dictionnaire contenant tous les composants de l'Ichimoku:
        - tenkan_sen: Ligne de conversion
        - kijun_sen: Ligne de base
        - senkou_span_a: Ligne avancée A
        - senkou_span_b: Ligne avancée B
        - chikou_span: Lagging span
    """
    # Tenkan-sen (Conversion Line): (highest high + lowest low)/2 pour les 9 dernières périodes
    tenkan_sen = (high.rolling(window=tenkan).max() + low.rolling(window=tenkan).min()) / 2

    # Kijun-sen (Base Line): (highest high + lowest low)/2 pour les 26 dernières périodes
    kijun_sen = (high.rolling(window=kijun).max() + low.rolling(window=kijun).min()) / 2

    # Senkou Span A (Leading Span A): (Tenkan-sen + Kijun-sen)/2 décalé de 26 périodes
    senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(displacement)

    # Senkou Span B (Leading Span B): (highest high + lowest low)/2 pour les 52 dernières périodes décalé de 26 périodes
    senkou_span_b = ((high.rolling(window=senkou_span_b).max() + low.rolling(window=senkou_span_b).min()) / 2).shift(displacement)

    # Chikou Span (Lagging Span): prix de clôture tracé 26 périodes en arrière.
    # IMPORTANT — causale uniquement : la valeur du Chikou à l'instant t est
    # close(t). La forme `close.shift(-displacement)` utilisait des clôtures
    # FUTURES (look-ahead) ; on la remplace par close() pour un backtest honnête.
    chikou_span = close.copy()

    return {
        "tenkan_sen": tenkan_sen,
        "kijun_sen": kijun_sen,
        "senkou_span_a": senkou_span_a,
        "senkou_span_b": senkou_span_b,
        "chikou_span": chikou_span,
    }


def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series,
                  period: int = 14) -> pd.Series:
    """
    Calcule le Volume Weighted Average Price (VWAP).

    Args:
        high: Série des prix hauts
        low: Série des prix bas
        close: Série des prix de clôture
        volume: Série des volumes
        period: Période pour le calcul (défaut: 14)

    Returns:
        Série contenant les valeurs du VWAP
    """
    volume = volume.replace(0, np.nan)
    typical_price = (high + low + close) / 3
    vwap = (typical_price * volume).rolling(window=period).sum() / volume.rolling(window=period).sum()
    return vwap


def detect_divergence(price: pd.Series, indicator: pd.Series, lookback: int = 10) -> Tuple[bool, bool]:
    """
    Détecte les divergences régulière entre le prix et un indicateur.

    Args:
        price: Série des prix de clôture
        indicator: Série de l'indicateur (RSI, MACD, etc.)
        lookback: Nombre de périodes à regarder en arrière pour détecter les divergences

    Returns:
        Tuple de (bullish_divergence, bearish_divergence)
    """
    if len(price) < lookback + 1 or len(indicator) < lookback + 1:
        return False, False

    # Trouver les hauts et bas récents dans le prix et l'indicateur
    recent_price = price.iloc[-lookback:]
    recent_indicator = indicator.iloc[-lookback:]

    # Pour la divergence haussière: prix fait un plus bas, indicateur fait un plus haut
    price_low = recent_price.iloc[-1] == recent_price.min()
    indicator_high = recent_indicator.iloc[-1] == recent_indicator.max()
    bullish_div = price_low and indicator_high

    # Pour la divergence baissière: prix fait un plus haut, indicateur fait un plus bas
    price_high = recent_price.iloc[-1] == recent_price.max()
    indicator_low = recent_indicator.iloc[-1] == recent_indicator.min()
    bearish_div = price_high and indicator_low

    return bullish_div, bearish_div


def calculate_kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """
    Calcule la fraction de Kelly optimale.

    Args:
        win_rate: Taux de réussite (0-1)
        avg_win: Gain moyen en pourcentage ou en monnaie de compte
        avg_loss: Perte moyenne en pourcentage ou en monnaie de compte (valeur positive)

    Returns:
        Fraction de Kelly (0-1)
    """
    if avg_win <= 0 or avg_loss <= 0:
        return 0.0

    # Formule de Kelly: f = (bp - q) / b
    # où b = avg_win/avg_loss, p = win_rate, q = 1 - win_rate
    if win_rate <= 0 or win_rate >= 1:
        return 0.0

    b = avg_win / avg_loss
    p = win_rate
    q = 1 - win_rate

    kelly = (b * p - q) / b
    return max(0.0, min(kelly, 1.0))  # Limiter entre 0 et 1


def calculate_risk_reward_ratio(entry_price: float, stop_loss: float, take_profit: float) -> float:
    """
    Calcule le ratio risque/rendement (RRR).

    Args:
        entry_price: Prix d'entrée
        stop_loss: Prix du stop loss
        take_profit: Prix du take profit

    Returns:
        Ratio risque/rendement (ex: 2.0 pour un R:R de 2:1)
    """
    if entry_price == stop_loss:
        return 0.0

    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)

    if risk == 0:
        return 0.0

    return reward / risk


def is_market_trending(adx_value: float, threshold: float = 22.0) -> bool:
    """
    Détermine si le marché est en tendance ou en phase de range basé sur l'ADX.

    Args:
        adx_value: Valeur actuelle de l'ADX
        threshold: Seuil au-dessus duquel on considère le marché comme tendance (défaut: 22.0)

    Returns:
        True si le marché est en tendance, False si en range
    """
    return adx_value > threshold


def calculate_position_size_from_risk(account_balance: float, risk_percent: float,
                                    entry_price: float, stop_loss: float) -> float:
    """
    Calcule la taille de position basée sur le risque en pourcentage du compte.

    Args:
        account_balance: Solde du compte
        risk_percent: Pourcentage du compte à risquer (ex: 1.0 pour 1%)
        entry_price: Prix d'entrée prévu
        stop_loss: Prix du stop loss

    Returns:
        Taille de position en unités de l'actif
    """
    if entry_price == stop_loss:
        return 0.0

    risk_amount = account_balance * (risk_percent / 100.0)
    price_risk = abs(entry_price - stop_loss)

    if price_risk == 0:
        return 0.0

    return risk_amount / price_risk


def round_to_precision(value: float, precision: int) -> float:
    """
    Arrondit une valeur à une précision spécifique.

    Args:
        value: Valeur à arrondir
        precision: Nombre de décimales

    Returns:
        Valeur arrondie
    """
    factor = 10 ** precision
    return round(value * factor) / factor


def calculate_pip_value(symbol: str, lot_size: float = 100000.0) -> float:
    """
    Calcule la valeur d'un pip pour une paire de devises donnée.

    Args:
        symbol: Symbole de la paire (ex: EUR/USD)
        lot_size: Taille du lot en unités de devise de base (défaut: 100,000 pour un lot standard)

    Returns:
        Valeur d'un pip en devise de quote
    """
    # Normaliser le symbole
    symbol = symbol.upper().replace("/", "")

    # Pour les paires où JPY est la devise de quote
    if "JPY" in symbol and symbol.endswith("JPY"):
        # Pour les paires JPY, un pip est 0.01
        return 0.01 * lot_size
    else:
        # Pour la plupart des autres paires, un pip est 0.0001
        return 0.0001 * lot_size


# Fonctions utilitaires pour l'analyse de données
def resample_data(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Rééchantillonne un DataFrame OHLCV vers un timeframe supérieur.

    Args:
        df: DataFrame avec colonnes ['open', 'high', 'low', 'close', 'volume'] et index datetime
        timeframe: Nouveau timeframe (ex: '4H', '1D', '1W')

    Returns:
        DataFrame rééchantillonné
    """
    ohlc_dict = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }
    return df.resample(timeframe).apply(ohlc_dict).dropna()


def get_higher_timeframe_data(df: pd.DataFrame, htf_multiplier: int = 4) -> pd.DataFrame:
    """
    Obtient les données d'un timeframe supérieur basé sur le timeframe actuel.

    Args:
        df: DataFrame avec données OHLCV
        htf_multiplier: Multiplicateur pour déterminer le timeframe supérieur (défaut: 4)

    Returns:
        DataFrame avec les données du timeframe supérieur
    """
    # Cette fonction serait plus sophistiquée dans une implémentation complète
    # Pour l'instant, on retourne une copie simple
    return df.copy()


def utc_bar_times(df: pd.DataFrame):
    """
    Horodatages UTC réels des barres. Les bougies MT5 sont indexées en heure serveur
    (UTC+2/+3) et portent le décalage dans la colonne `server_utc_offset_s` ; sans cette
    colonne (backtest, données déjà en UTC), l'index est retourné tel quel.
    """
    if 'server_utc_offset_s' in df.columns and len(df) > 0:
        offset = df['server_utc_offset_s'].iloc[-1]
        if pd.notna(offset) and offset:
            return df.index - pd.Timedelta(seconds=float(offset))
    return df.index


_TF_SECONDS = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}


def closed_bar_age_seconds(df: pd.DataFrame, granularity: str, now=None) -> float:
    """Secondes écoulées depuis la clôture de la dernière barre de `df` (barre supposée clôturée)."""
    unit = granularity.strip().lower()[-1]
    tf_s = int(granularity.strip()[:-1]) * _TF_SECONDS[unit]
    opened = pd.Timestamp(utc_bar_times(df)[-1])
    if opened.tzinfo is None:
        opened = opened.tz_localize('UTC')
    now = pd.Timestamp.now(tz='UTC') if now is None else pd.Timestamp(now)
    if now.tzinfo is None:
        now = now.tz_localize('UTC')
    return (now - (opened + pd.Timedelta(seconds=tf_s))).total_seconds()


def calculate_asian_range(df: pd.DataFrame) -> tuple:
    """
    Calcule le range de la session asiatique (00:00–06:59 UTC) du jour UTC courant.

    Args:
        df: DataFrame OHLCV avec index DatetimeIndex.

    Returns:
        Tuple (asian_high, asian_low, asian_range).
        Si aucune donnée asiatique n'est trouvée, retourne les 10 dernières bougies.
    """
    if df is None or len(df) < 5:
        return 0.0, 0.0, 0.0

    if hasattr(df.index, 'hour'):
        times = utc_bar_times(df)
        asian_mask = (times.hour >= 0) & (times.hour < 7) & (times.date == times[-1].date())
        asian_bars = df.loc[asian_mask]
    else:
        asian_bars = pd.DataFrame()

    if asian_bars.empty or len(asian_bars) < 2:
        # Fallback : utiliser les 10 dernières bougies
        asian_bars = df.iloc[-10:]

    asian_high = float(asian_bars['high'].max())
    asian_low = float(asian_bars['low'].min())
    asian_range = asian_high - asian_low

    return asian_high, asian_low, asian_range


def calculate_hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """
    Calcule l'exposant de Hurst via la loi de diffusion / variance-scaling (Ernest Chan).

    std(y_{t+tau} - y_t) ~ tau^H

    H > 0.55 : série persistante (tendance forte)
    H ~ 0.50 : marche aléatoire (bruit brownien)
    H < 0.45 : série anti-persistante (retour à la moyenne / stationnaire)
    """
    if series is None or len(series) < 20:
        return 0.5

    ts = np.asarray(series.dropna(), dtype=float)
    n = len(ts)
    if n < 20:
        return 0.5

    lags = range(2, min(max_lag + 1, n // 4))
    tau = []
    lagvec = []

    for lag in lags:
        diffs = ts[lag:] - ts[:-lag]
        std_val = np.std(diffs)
        if std_val > 1e-10:
            tau.append(std_val)
            lagvec.append(lag)

    if len(lagvec) < 3:
        return 0.5

    try:
        poly = np.polyfit(np.log(lagvec), np.log(tau), 1)
        hurst = float(poly[0])
        return max(0.0, min(1.0, hurst))
    except (np.linalg.LinAlgError, ValueError):
        return 0.5


def calculate_half_life(series: pd.Series) -> float:
    """
    Calcule la demi-vie d'Ornstein-Uhlenbeck (Ernest Chan).

    Régression OLS : Δy_t = β * y_{t-1} + ε
    Demi-vie = -ln(2) / β

    Args:
        series: Série de prix (close).

    Returns:
        Demi-vie en barres (float). Valeur par défaut 20.0 si incalculable.
    """
    if series is None or len(series) < 10:
        return 20.0

    ts = np.asarray(series.dropna(), dtype=float)
    if len(ts) < 10:
        return 20.0

    ts_lag = ts[:-1]
    ts_diff = np.diff(ts)

    if np.std(ts_lag) < 1e-10:
        return 20.0

    try:
        beta, _ = np.polyfit(ts_lag, ts_diff, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 20.0

    if beta >= 0:
        return 100.0  # Non mean-reverting

    half_life = -np.log(2) / beta
    return float(np.clip(half_life, 1.0, 500.0))


# Export des fonctions publiques
__all__ = [
    'calculate_atr', 'calculate_ema', 'calculate_sma', 'calculate_rsi',
    'calculate_macd', 'calculate_adx', 'calculate_supertrend',
    'calculate_bollinger_bands', 'calculate_ichimoku', 'calculate_vwap',
    'detect_divergence', 'calculate_kelly_fraction', 'calculate_risk_reward_ratio',
    'is_market_trending', 'calculate_position_size_from_risk',
    'round_to_precision', 'calculate_pip_value', 'resample_data',
    'get_higher_timeframe_data',
    'calculate_asian_range',
    'calculate_hurst_exponent', 'calculate_half_life',
]