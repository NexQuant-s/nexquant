"""
NexQuant SuperBot — Spécifications des Symboles Forex & Matières Premières MT5
=============================================================================
Module de référence pour la modélisation mathématique et contractuelle de tous
les instruments traités :
- Matières Premières (Or, Argent, Pétrole WTI/Brent, Gaz Naturel)
- Devises Forex (Majeures, JPY, Cross)
"""

import math
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from superbot.config import MT5_CRYPTO_SYMBOLS  # noqa: F401 — réexporté (orchestrator, tests)


# Classification des symboles et alias des courtiers
COMMODITY_ALIASES: Dict[str, str] = {
    # Gold
    "XAUUSD": "XAUUSD",
    "GOLD": "XAUUSD",
    "XAU/USD": "XAUUSD",
    "XAUUSD.M": "XAUUSD",
    "XAUUSD_I": "XAUUSD",
    # Silver
    "XAGUSD": "XAGUSD",
    "SILVER": "XAGUSD",
    "XAG/USD": "XAGUSD",
    # WTI Oil
    "XTIUSD": "XTIUSD",
    "WTI": "XTIUSD",
    "WTIUSD": "XTIUSD",
    "OIL": "XTIUSD",
    "WTICRUDE": "XTIUSD",
    "USOIL": "XTIUSD",
    "USOILCASH": "XTIUSD",
    "WTICASH": "XTIUSD",
    "CL": "XTIUSD",
    # Brent Oil
    "XBRUSD": "XBRUSD",
    "BRENT": "XBRUSD",
    "BRENTUSD": "XBRUSD",
    "UKOIL": "XBRUSD",
    "UKOILCASH": "XBRUSD",
    "BRN": "XBRUSD",
    # Natural Gas
    "XNGUSD": "XNGUSD",
    "NGAS": "XNGUSD",
    "NATGAS": "XNGUSD",
    "GAS": "XNGUSD",
}

# Spécifications standard par défaut (utilisées en fallback si MT5 hors-ligne)
DEFAULT_SPECS: Dict[str, Dict[str, Any]] = {
    # Matières Premières
    "XAUUSD": {
        "asset_class": "commodity_gold",
        "contract_size": 100.0,      # 1 lot = 100 onces troy
        "digits": 2,
        "point": 0.01,
        "pip_size": 0.10,            # 1 pip d'or = 10 cents = $10 par lot
        "max_spread_pips": 3.0,      # Spread max acceptable (ex: $0.30)
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "XAGUSD": {
        "asset_class": "commodity_silver",
        "contract_size": 5000.0,     # 1 lot = 5000 onces troy
        "digits": 3,
        "point": 0.001,
        "pip_size": 0.01,            # 1 pip d'argent = 1 cent = $50 par lot
        "max_spread_pips": 4.0,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "XTIUSD": {
        "asset_class": "commodity_oil",
        "contract_size": 1000.0,     # 1 lot = 1000 barils
        "digits": 2,
        "point": 0.01,
        "pip_size": 0.01,            # 1 pip de pétrole = 1 cent = $10 par lot
        "max_spread_pips": 4.0,      # Spread max 4 cents
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "XBRUSD": {
        "asset_class": "commodity_oil",
        "contract_size": 1000.0,     # 1 lot = 1000 barils
        "digits": 2,
        "point": 0.01,
        "pip_size": 0.01,
        "max_spread_pips": 4.0,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "XNGUSD": {
        "asset_class": "commodity_gas",
        "contract_size": 10000.0,    # 1 lot = 10000 MMBtu
        "digits": 3,
        "point": 0.001,
        "pip_size": 0.01,
        "max_spread_pips": 5.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
    # Forex Majeures (5 décimales)
    "EURUSD": {
        "asset_class": "forex_major",
        "contract_size": 100000.0,   # 1 lot = 100 000 EUR
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,          # 1 pip = 0.0001 = $10 par lot
        "max_spread_pips": 1.8,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "GBPUSD": {
        "asset_class": "forex_major",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 2.2,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "AUDUSD": {
        "asset_class": "forex_major",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 2.0,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "NZDUSD": {
        "asset_class": "forex_major",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 2.5,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "USDCAD": {
        "asset_class": "forex_major",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 2.2,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "USDCHF": {
        "asset_class": "forex_major",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 2.2,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    # Forex JPY (3 décimales)
    "USDJPY": {
        "asset_class": "forex_jpy",
        "contract_size": 100000.0,
        "digits": 3,
        "point": 0.001,
        "pip_size": 0.01,            # 1 pip = 0.01 JPY
        "max_spread_pips": 2.0,
        "default_sl_atr": 1.8,
        "default_tp_atr": 3.5,
    },
    "EURJPY": {
        "asset_class": "forex_jpy",
        "contract_size": 100000.0,
        "digits": 3,
        "point": 0.001,
        "pip_size": 0.01,
        "max_spread_pips": 2.5,
        "default_sl_atr": 1.8,
        "default_tp_atr": 3.5,
    },
    "GBPJPY": {
        "asset_class": "forex_jpy",
        "contract_size": 100000.0,
        "digits": 3,
        "point": 0.001,
        "pip_size": 0.01,
        "max_spread_pips": 3.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
    # Forex Cross
    "EURGBP": {
        "asset_class": "forex_cross",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 2.0,
        "default_sl_atr": 1.5,
        "default_tp_atr": 3.0,
    },
    "EURAUD": {
        "asset_class": "forex_cross",
        "contract_size": 100000.0,
        "digits": 5,
        "point": 0.00001,
        "pip_size": 0.0001,
        "max_spread_pips": 3.0,
        "default_sl_atr": 1.8,
        "default_tp_atr": 3.5,
    },
    # Crypto CFDs (Actifs 24/7 pour le trading exclusif du weekend)
    "BTCUSD": {
        "asset_class": "crypto",
        "contract_size": 1.0,
        "digits": 2,
        "point": 0.01,
        "pip_size": 1.0,
        "max_spread_pips": 50.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
    "ETHUSD": {
        "asset_class": "crypto",
        "contract_size": 1.0,
        "digits": 2,
        "point": 0.01,
        "pip_size": 0.10,
        "max_spread_pips": 20.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
    "BNBUSD": {
        "asset_class": "crypto",
        "contract_size": 1.0,
        "digits": 2,
        "point": 0.01,
        "pip_size": 0.10,
        "max_spread_pips": 10.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
    "XRPUSD": {
        "asset_class": "crypto",
        "contract_size": 1.0,
        "digits": 4,
        "point": 0.0001,
        "pip_size": 0.001,
        "max_spread_pips": 5.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
    "SOLUSD": {
        "asset_class": "crypto",
        "contract_size": 1.0,
        "digits": 2,
        "point": 0.01,
        "pip_size": 0.10,
        "max_spread_pips": 10.0,
        "default_sl_atr": 2.0,
        "default_tp_atr": 4.0,
    },
}


def normalize_symbol_name(symbol: str) -> str:
    """
    Normalise le nom du symbole en majuscules sans délimiteur
    et résout les alias de matières premières.
    Ex: 'EUR/USD' -> 'EURUSD', 'GOLD' -> 'XAUUSD', 'WTI' -> 'XTIUSD'.
    """
    if not symbol:
        return ""
    stripped = symbol.strip().upper()
    if stripped in COMMODITY_ALIASES:
        return COMMODITY_ALIASES[stripped]
    clean = stripped.replace("/", "").replace(".", "").replace("-", "")
    return COMMODITY_ALIASES.get(clean, clean)


def get_asset_class(symbol: str) -> str:
    """
    Détecte la classe d'actifs exacte d'un symbole MT5.
    Retourne :
      - 'commodity_gold'
      - 'commodity_silver'
      - 'commodity_oil'
      - 'commodity_gas'
      - 'forex_jpy'
      - 'forex_major'
      - 'forex_cross'
    """
    norm = normalize_symbol_name(symbol)
    if norm in DEFAULT_SPECS:
        return DEFAULT_SPECS[norm]["asset_class"]

    # Règle heuristique
    if "XAU" in norm or "GOLD" in norm:
        return "commodity_gold"
    if "XAG" in norm or "SILVER" in norm:
        return "commodity_silver"
    if "XTI" in norm or "XBR" in norm or "OIL" in norm or "WTI" in norm or "BRENT" in norm:
        return "commodity_oil"
    if "XNG" in norm or "GAS" in norm:
        return "commodity_gas"
    if "JPY" in norm:
        return "forex_jpy"
    
    # Crypto CFDs
    if any(c in norm for c in ["BTC", "ETH", "BNB", "XRP", "SOL"]):
        return "crypto"

    # Forex majeur vs cross
    majors = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "NZDUSD", "USDCAD", "USDCHF"]
    if norm in majors:
        return "forex_major"
    return "forex_cross"


_detect_asset_class_mt5 = get_asset_class


def is_weekend_market(dt_utc: Optional[datetime] = None) -> bool:
    """
    Vérifie si les marchés traditionnels (Forex & Matières Premières) sont fermés pour le week-end.
    Fermeture : Vendredi à partir de 22h00 UTC
    Réouverture : Dimanche à partir de 21h00 UTC
    Pendant cette période, seules les cryptomonnaies sont scannées et traitées.
    """
    if dt_utc is None:
        dt_utc = datetime.now(timezone.utc)
    weekday = dt_utc.weekday()
    hour = dt_utc.hour
    if weekday == 4 and hour >= 22:
        return True
    if weekday == 5:
        return True
    if weekday == 6 and hour < 21:
        return True
    return False


def get_pip_size(symbol: str, digits: Optional[int] = None) -> float:
    """
    Retourne la taille d'un pip standard pour le symbole.
    - Forex 5 digits -> 0.0001 (10 points)
    - Forex JPY 3 digits -> 0.01 (10 points)
    - Or (XAUUSD) -> 0.10
    - Pétrole (XTIUSD/XBRUSD) -> 0.01
    """
    norm = normalize_symbol_name(symbol)
    if norm in DEFAULT_SPECS:
        return DEFAULT_SPECS[norm]["pip_size"]

    asset_cls = get_asset_class(norm)
    if asset_cls == "commodity_gold":
        return 0.10

    if digits is not None:
        if digits == 5 or digits == 4:
            return 0.0001
        elif digits == 3 or digits == 2:
            return 0.01

    if asset_cls in ["commodity_oil", "commodity_silver", "forex_jpy"]:
        return 0.01
    return 0.0001


def is_rollover_period(utc_hour: Optional[int] = None, utc_minute: Optional[int] = None) -> bool:
    """
    Vérifie si le moment actuel correspond à la fenêtre de rollover interbancaire
    (21:55 UTC -> 23:05 UTC) où les spreads s'écartent fortement.
    Le trading doit être suspendu pendant cette fenêtre pour éviter les faux déclenchements.
    """
    if utc_hour is None or utc_minute is None:
        now = datetime.now(timezone.utc)
        utc_hour = now.hour if utc_hour is None else utc_hour
        utc_minute = now.minute if utc_minute is None else utc_minute

    if utc_hour == 21 and utc_minute >= 55:
        return True
    if utc_hour == 22:
        return True
    if utc_hour == 23 and utc_minute <= 5:
        return True
    return False


def get_active_sessions(utc_hour: Optional[int] = None) -> list:
    """
    Détermine les sessions de marché actives en heure UTC.
    - ASIA      : 00:00 -> 09:00 UTC (Tokyo / Singapour / Sydney)
    - LONDON    : 07:00 -> 16:00 UTC (Londres)
    - OVERLAP   : 12:00 -> 16:00 UTC (Londres + New York - pic de liquidité mondiale)
    - NEW_YORK  : 12:00 -> 21:00 UTC (New York)
    - OFF_HOURS : 21:00 -> 23:59 UTC (Interbancaire / Rollover / Faible liquidité)
    """
    if utc_hour is None:
        utc_hour = datetime.now(timezone.utc).hour

    sessions = []
    if 0 <= utc_hour < 9:
        sessions.append("ASIA")
    if 7 <= utc_hour < 16:
        sessions.append("LONDON")
    if 12 <= utc_hour < 16:
        sessions.append("OVERLAP")
    if 12 <= utc_hour < 21:
        sessions.append("NEW_YORK")
    if not sessions:
        sessions.append("OFF_HOURS")
    return sessions


def calculate_lot_size(
    account_balance: float,
    risk_pct: float,
    entry_price: float,
    sl_price: float,
    contract_size: float = 100000.0,
    tick_size: float = 0.00001,
    tick_value: float = 1.0,
    volume_min: float = 0.01,
    volume_step: float = 0.01,
    volume_max: float = 100.0,
    symbol: str = "",
) -> float:
    """
    Calcule la taille de position exacte en lots MT5 selon la formule institutionnelle :

    Risque (€/$) = account_balance * (risk_pct / 100)
    Distance de stop (points/ticks) = |entry_price - sl_price| / tick_size
    Valeur du risque par lot = Distance_ticks * tick_value
    Lots = Risque_total / Valeur_risque_par_lot

    Ajusté strictement selon volume_min, volume_step et volume_max.
    """
    if math.isnan(entry_price) or math.isnan(sl_price) or math.isinf(entry_price) or math.isinf(sl_price):
        return volume_min

    if account_balance <= 0 or risk_pct <= 0:
        return 0.0

    stop_distance_price = abs(entry_price - sl_price)
    if stop_distance_price <= 0:
        return 0.0

    risk_amount_currency = account_balance * (risk_pct / 100.0)

    # Si tick_size ou tick_value ne sont pas fournis, calcul analytique
    if tick_size <= 0:
        tick_size = 0.00001
    if tick_value <= 0:
        # Estimation : contract_size * tick_size
        tick_value = contract_size * tick_size

    # Nombre de ticks dans la distance de stop
    ticks_at_risk = stop_distance_price / tick_size
    risk_per_lot = ticks_at_risk * tick_value

    if risk_per_lot <= 0:
        return 0.0

    raw_lots = risk_amount_currency / risk_per_lot

    # Si le volume calculé est inférieur au minimum requis par le courtier,
    # on ne force PAS à la hausse pour éviter la sur-exposition sur petit compte.
    if raw_lots < (volume_min - 1e-7):
        return 0.0

    # Arrondi au pas de volume (volume_step) avec tolérance IEEE-754
    steps = math.floor(round(raw_lots / volume_step, 6))
    adjusted_lots = round(steps * volume_step, 4)

    # Limites courtier
    adjusted_lots = min(adjusted_lots, volume_max)

    return adjusted_lots
