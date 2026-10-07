import logging
from typing import Dict, Any, Tuple
log = logging.getLogger(__name__)

def calculate_sl_tp_levels(rm, entry_price: float, atr_value: float,
                              position_side: str, asset_type: str = "forex",
                              symbol: str = "",
                              hmm_regime: str = "") -> Tuple[float, float]:
    """
    Calcule les niveaux de stop loss et take profit basés sur l'ATR, avec multiplicateurs selon l'actif.

    Le paramètre `symbol` détecte automatiquement les paires JPY et applique des
    multiplicateurs ATR plus larges (2.0×SL / 4.0×TP) pour compenser leur plus grande
    amplitude intra-journalière.

    SL/TP adaptatifs par régime HMM : le paramètre `hmm_regime` (ex: 'HIGH_VOL_RANGE',
    'LOW_VOL_RANGE', 'TRENDING', 'LOW_VOL_TREND') ajuste les multiplicateurs pour éviter
    les sorties prématurées en haute volatilité, ou pour serrer les stops en régime calme.

    Règles :
      - HIGH_VOL_RANGE  : +40% SL, +40% TP (évite les whipsaws)
      - LOW_VOL_RANGE   : -15% SL, -15% TP (marché calme, cibles plus proches)
      - TRENDING        : multiplicateurs standards
      - LOW_VOL_TREND   : -10% SL (tendance propre, moins de bruit)
    """
    # Détecter la classe d'actif exacte selon le symbole
    effective_asset_type = asset_type
    if symbol:
        from superbot.broker.symbol_specs import get_asset_class
        symbol_class = get_asset_class(symbol)
        if symbol_class == "crypto":
            effective_asset_type = "crypto"
            log.debug(f"Multiplicateurs crypto appliqués pour {symbol}: SL=2.5×ATR, TP=5.0×ATR")
        elif symbol_class == "forex_jpy" or (symbol.strip().upper().replace("/", "").endswith("JPY") and asset_type == "forex"):
            effective_asset_type = "forex_jpy"
            log.debug(f"Multiplicateurs ATR élargis appliqués pour paire JPY {symbol}: SL=2.0×ATR, TP=4.0×ATR")
        elif symbol_class.startswith("commodity"):
            effective_asset_type = "commodity"

    if atr_value <= 0:
        risk_pct = 0.02
        if position_side == "LONG":
            sl_price = entry_price * (1 - risk_pct)
            tp_price = entry_price * (1 + risk_pct * 2)
        else:
            sl_price = entry_price * (1 + risk_pct)
            tp_price = entry_price * (1 - risk_pct * 2)
        return sl_price, tp_price

    # 🧠 V3 : Smart SL/TP multipliers (Target-Aware)
    if hasattr(rm, 'get_regime_sl_tp_multipliers'):
        mults = rm.get_regime_sl_tp_multipliers(
            regime=hmm_regime, asset_class=effective_asset_type,
            base_sl=getattr(rm, 'SL_ATR_MULT', 1.5), base_tp=getattr(rm, 'TP_ATR_MULT', 3.0),
        )
        sl_mult = mults.get('sl_atr_mult', 1.5)
        tp_mult = mults.get('tp_atr_mult', 3.0)
    else:
        mults = rm.ATR_MULTIPLIERS.get(effective_asset_type, rm.ATR_MULTIPLIERS['forex'])
        sl_mult, tp_mult = mults['sl'], mults['tp']

        # Modulation des multiplicateurs par régime HMM
        regime_upper = hmm_regime.upper() if hmm_regime else ""
        if regime_upper == "HIGH_VOL_RANGE":
            # Haute volatilité : écarter SL et TP pour éviter les whipsaws
            sl_mult *= 1.40
            tp_mult *= 1.40
            log.debug(f"[Régime HMM] HIGH_VOL_RANGE → SL×1.4={sl_mult:.2f}, TP×1.4={tp_mult:.2f} pour {symbol}")
        elif regime_upper == "LOW_VOL_RANGE":
            # Marché calme : objectifs plus proches, moins de bruit
            sl_mult *= 0.85
            tp_mult *= 0.85
            log.debug(f"[Régime HMM] LOW_VOL_RANGE → SL×0.85={sl_mult:.2f}, TP×0.85={tp_mult:.2f} pour {symbol}")
        elif regime_upper == "LOW_VOL_TREND":
            # Tendance propre et calme : SL légèrement plus serré (moins de bruit)
            sl_mult *= 0.90
            log.debug(f"[Régime HMM] LOW_VOL_TREND → SL×0.90={sl_mult:.2f} pour {symbol}")
        # TRENDING et cas inconnus : multiplicateurs standards (pas de modification)

    sl_dist = sl_mult * atr_value
    tp_dist = tp_mult * atr_value
    
    # Minimum SL distances by asset class
    MIN_SL_DISTANCES = {
        'FOREX_MAJOR': 0.0012,    # 12 pips
        'FOREX_JPY': 0.15,         # 15 pips for JPY pairs
        'FOREX_CROSS': 0.0012,     # 12 pips
        'GOLD': 8.0,               # $8 for XAUUSD
        'SILVER': 0.30,            # $0.30 for XAGUSD
        'OIL': 0.50,               # $0.50 for oil
        'GAS': 0.020,              # for XNGUSD
        'CRYPTO': None,            # handled separately (0.35% of price)
    }

    if symbol:
        sym = symbol.strip().upper().replace("/", "")
        asset_key = None
        if effective_asset_type == "crypto":
            asset_key = 'CRYPTO'
        elif 'XAU' in sym or 'GOLD' in sym:
            asset_key = 'GOLD'
        elif 'XAG' in sym or 'SILVER' in sym:
            asset_key = 'SILVER'
        elif 'USO' in sym or 'WTI' in sym or 'OIL' in sym or 'BRENT' in sym:
            asset_key = 'OIL'
        elif 'XNG' in sym or 'GAS' in sym:
            asset_key = 'GAS'
        elif 'JPY' in sym:
            asset_key = 'FOREX_JPY'
        elif len(sym) >= 6:
            asset_key = 'FOREX_MAJOR'
            
        if asset_key and asset_key in MIN_SL_DISTANCES and MIN_SL_DISTANCES[asset_key] is not None:
            min_sl = MIN_SL_DISTANCES[asset_key]
            if sl_dist < min_sl:
                sl_dist = min_sl
                tp_dist = max(tp_dist, sl_dist * 2.0)

    if effective_asset_type == "crypto" and entry_price > 0:
        min_crypto_sl = entry_price * 0.0035  # ~270$ sur BTC à 77000$ pour absorber le bruit
        if sl_dist < min_crypto_sl:
            sl_dist = min_crypto_sl
            tp_dist = max(tp_dist, sl_dist * 2.0)

    if position_side == "LONG":
        sl_price = entry_price - sl_dist
        tp_price = entry_price + tp_dist
    else:
        sl_price = entry_price + sl_dist
        tp_price = entry_price - tp_dist

    return max(0.0001, sl_price), max(0.0001, tp_price)

def _check_trailing_stop(rm, symbol: str, position: Dict[str, Any], current_price: float):
    """
    Vérifie et met à jour le stop loss suiveur si les conditions sont remplies.

    Args:
        symbol: Symbole de la position
        position: Dictionnaire de la position
        current_price: Prix actuel du marché
    """
    # Vérifier si le trailing stop est activé pour cette position
    if not position.get('trailing_stop_enabled', True):
        return

    try:
        atr_value = position.get('atr_value', 0)
        if atr_value <= 0:
            return

        entry_price = position.get('entry_price', 0)
        activate_mult = getattr(rm, 'TRAIL_ACTIVATE_ATR_MULT', 1.0)

        if position['side'] == 'LONG':
            # Distance d'activation : le trailing ne démarre qu'une fois le trade
            # à +N×ATR en faveur. Avant cela, laisser le trade respirer au lieu
            # d'écraser les winners naissants dès le premier tick favorable.
            if entry_price > 0 and activate_mult > 0:
                profit_atr = (current_price - entry_price) / atr_value
                if profit_atr < activate_mult:
                    return
            # Pour une position longue, le trailing stop monte quand le prix monte
            new_sl = current_price - (rm.TRAIL_ATR_MULT * atr_value)
            # Ne jamais descendre le stop loss pour une position longue
            if new_sl > position.get('stop_loss', 0):
                old_sl = position.get('stop_loss', 0)
                position['stop_loss'] = new_sl
                log.info(f"Trailing stop mis à jour pour {symbol} (LONG): {old_sl:.4f} -> {new_sl:.4f}")
        else:  # SHORT
            if entry_price > 0 and activate_mult > 0:
                profit_atr = (entry_price - current_price) / atr_value
                if profit_atr < activate_mult:
                    return
            # Pour une position courte, le trailing stop descend quand le prix descend
            new_sl = current_price + (rm.TRAIL_ATR_MULT * atr_value)
            current_sl = position.get('stop_loss', 0)
            sl_not_set = (current_sl == 0 or current_sl is None)
            # Ne jamais remonter le stop d'une position courte.
            if sl_not_set or new_sl < current_sl:
                old_sl = current_sl
                position['stop_loss'] = new_sl
                log.info(f"Trailing stop mis à jour pour {symbol} (SHORT): {old_sl:.4f} -> {new_sl:.4f}")

    except Exception as e:
        log.error(f"Erreur lors de la vérification du trailing stop pour {symbol}: {e}")

def _check_break_even(rm, symbol: str, position: Dict[str, Any], current_price: float):
    """
    Vérifie et déplace le stop loss au point d'entrée si les conditions sont remplies.

    Args:
        symbol: Symbole de la position
        position: Dictionnaire de la position
        current_price: Prix actuel du marché
    """
    # Vérifier si le break-even est activé et pas déjà activé
    if position.get('break_even_activated', False):
        return

    try:
        atr_value = position.get('atr_value', 0)
        if atr_value <= 0:
            return

        # Déterminer si le break-even doit se déclencher
        should_trigger = False
        if rm.BE_DYN_RR:
            initial_sl = position.get('initial_sl', 0.0)
            if position['side'] == 'LONG':
                initial_risk = position['entry_price'] - initial_sl
                current_profit = current_price - position['entry_price']
                should_trigger = (initial_risk > 0 and current_profit >= initial_risk * rm.BE_DYN_RR_RATIO)
            else: # SHORT
                initial_risk = initial_sl - position['entry_price']
                current_profit = position['entry_price'] - current_price
                should_trigger = (initial_risk > 0 and current_profit >= initial_risk * rm.BE_DYN_RR_RATIO)
        else:
            if position['side'] == 'LONG':
                profit_in_atr = (current_price - position['entry_price']) / atr_value
                should_trigger = (profit_in_atr >= rm.BE_ATR_MULT)
            else: # SHORT
                profit_in_atr = (position['entry_price'] - current_price) / atr_value
                should_trigger = (profit_in_atr >= rm.BE_ATR_MULT)

        if should_trigger:
            position['break_even_activated'] = True
            if position['side'] == 'LONG':
                old_sl = position.get('stop_loss', 0)
                new_sl = position['entry_price'] * 1.0005  # Légèrement au-dessus pour couvrir les frais
                if new_sl > old_sl:
                    position['stop_loss'] = new_sl
                    log.info(f"Break-even activé pour {symbol} (LONG): SL moved to {new_sl:.4f}")
                else:
                    log.info(f"Break-even activé pour {symbol} (LONG) mais le trailing stop actuel ({old_sl:.4f}) est meilleur que BE ({new_sl:.4f})")
            else:  # SHORT
                # `or float('inf')` car get('stop_loss', ...) retournerait 0 si la clé vaut 0.
                old_sl = position.get('stop_loss') or float('inf')
                new_sl = position['entry_price'] * 0.9995  # Légèrement en-dessous pour couvrir les frais
                if new_sl < old_sl or old_sl == 0:
                    position['stop_loss'] = new_sl
                    log.info(f"Break-even activé pour {symbol} (SHORT): SL moved to {new_sl:.4f}")
                else:
                    log.info(f"Break-even activé pour {symbol} (SHORT) mais le trailing stop actuel ({old_sl:.4f}) est meilleur que BE ({new_sl:.4f})")



    except Exception as e:
        log.error(f"Erreur lors de la vérification du break-even pour {symbol}: {e}")