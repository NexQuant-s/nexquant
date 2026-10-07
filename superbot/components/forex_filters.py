from datetime import datetime, timezone
import logging

log = logging.getLogger("forex_filters")


def is_market_open(symbol: str = "") -> bool:
    """
    Vérifie si au moins une session Forex majeure est actuellement ouverte.

    Sessions couvertes (UTC) :
      - Tokyo   : 23h00 – 08h00 UTC
      - Londres : 07h00 – 17h00 UTC
      - New York: 12h00 – 22h00 UTC

    Le bot peut ainsi trader H24 du lundi au vendredi,
    se mettant en pause uniquement le week-end (vendredi 22h UTC → dimanche 22h UTC).

    Returns:
        True si au moins une session est ouverte et ce n'est pas le week-end.
    """
    if symbol:
        from superbot.broker.symbol_specs import get_asset_class
        if get_asset_class(symbol) == "crypto":
            return True

    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    weekday = now_utc.weekday()  # 0=Lundi, 5=Samedi, 6=Dimanche

    # Blocage week-end : vendredi après 22h UTC, samedi tout le jour + dimanche avant 21h UTC (réouverture Sydney)
    if weekday == 4 and hour >= 22:  # Vendredi soir après 22h UTC
        log.debug(f"[MarketOpen] Marché fermé (Vendredi soir >22h UTC). Heure UTC: {now_utc.strftime('%H:%M')}")
        return False
    if weekday == 5:  # Samedi
        log.debug(f"[MarketOpen] Marché fermé (Samedi). Heure UTC: {now_utc.strftime('%H:%M')}")
        return False
    if weekday == 6 and hour < 21:  # Dimanche avant 21h UTC
        log.debug(f"[MarketOpen] Marché fermé (Dimanche <21h UTC). Heure UTC: {now_utc.strftime('%H:%M')}")
        return False

    # Du dimanche 21h00 UTC au vendredi 22h00 UTC, le marché Forex est ouvert H24 (Sydney + Tokyo + Londres + NY)
    return True


def check_spread(broker, symbol: str, max_spread: float) -> bool:
    """Vérifie si le spread de l'actif est acceptable."""
    spread = broker.get_spread(symbol)
    if spread > max_spread:
        log.info(f"🚫 Trade {symbol} rejeté : Spread trop large ({spread:.1f} pips > {max_spread} pips max)")
        return False
    return True

def check_currency_correlation(symbol: str, positions: dict, max_exposure: int, cand_side: str) -> bool:
    """
    Vérifie qu'on n'est pas trop exposé sur une seule devise de base ou de cotation.
    """
    clean = symbol.upper().replace("/", "")
    if len(clean) < 6:
        return True # Not a standard forex pair
    
    base_cand = clean[:3]
    quote_cand = clean[3:6]
    
    currency_exposure = {}
    for open_sym, pos in positions.items():
        if pos.get('size', 0) > 0:
            open_clean = open_sym.upper().replace("/", "")
            if len(open_clean) >= 6:
                op_base = open_clean[:3]
                op_quote = open_clean[3:6]
                op_side = pos.get('side', '').upper()
                
                if op_side in ['LONG', 'BUY']:
                    currency_exposure[op_base] = currency_exposure.get(op_base, 0) + 1
                    currency_exposure[op_quote] = currency_exposure.get(op_quote, 0) - 1
                elif op_side in ['SHORT', 'SELL']:
                    currency_exposure[op_base] = currency_exposure.get(op_base, 0) - 1
                    currency_exposure[op_quote] = currency_exposure.get(op_quote, 0) + 1

    if cand_side == 'LONG':
        new_base_exp = currency_exposure.get(base_cand, 0) + 1
        new_quote_exp = currency_exposure.get(quote_cand, 0) - 1
    else:
        new_base_exp = currency_exposure.get(base_cand, 0) - 1
        new_quote_exp = currency_exposure.get(quote_cand, 0) + 1

    if abs(new_base_exp) > max_exposure or abs(new_quote_exp) > max_exposure:
        log.info(
            f"🚫 Trade {symbol} rejeté : Risque de corrélation de devises trop élevé. "
            f"Exposition nette : {base_cand}={new_base_exp}, {quote_cand}={new_quote_exp} "
            f"(limite autorisée: +/- {max_exposure})"
        )
        return False
    return True

def check_pivot_obstacle(entry_price: float, sl_price: float, df_with_indicators, should_long: bool, symbol: str) -> bool:
    """
    Rejette le trade si un obstacle pivot majeur gâche le ratio R:R réel.
    """
    last_row = df_with_indicators.iloc[-1]
    r1 = last_row.get('r1', 0)
    s1 = last_row.get('s1', 0)
    r2 = last_row.get('r2', 0)
    s2 = last_row.get('s2', 0)

    target_obstacle = 0.0
    if should_long:
        obstacles = [val for val in [r1, r2] if val > entry_price]
        target_obstacle = min(obstacles) if obstacles else 0.0
    else:
        obstacles = [val for val in [s1, s2] if val < entry_price]
        target_obstacle = max(obstacles) if obstacles else 0.0

    if target_obstacle > 0:
        potential_gain = abs(target_obstacle - entry_price)
        potential_risk = abs(entry_price - sl_price)
        if potential_risk > 0:
            real_rr = potential_gain / potential_risk
            if real_rr < 1.0:
                log.info(f"🚫 Trade {symbol} rejeté : Obstacle pivot trop proche. R:R réel potentiel = {real_rr:.2f} < 1.0 (Obstacle à {target_obstacle:.5f})")
                return False
    return True

# =============================================================================
# FILTRE NEWS ÉCONOMIQUES MAJEURES (P1 — Spécifique Forex)
# =============================================================================
# Événements à impact extrêmement élevé qui provoquent des spreads ingérables,
# des slippages catastrophiques et des mouvements erratiques sur toutes les paires Forex.
# La stratégie doit bloquer tout trade ±N minutes autour de ces publications.

def check_major_news_window(symbol: str, avoid_minutes: int = 30, news_events: list = None) -> bool:
    """
    Bloque le trading Forex ±avoid_minutes autour des publications économiques majeures.
    
    La vérification est basée sur :
    1. La liste dynamique `news_events` fournie par le NewsManager (si disponible)
    2. Un fallback sur des règles horaires statiques pour NFP / Fed / BCE
    
    Args:
        symbol: Paire Forex (ex: "EURUSD")
        avoid_minutes: Minutes à éviter avant et après chaque publication (défaut: 30)
        news_events: Liste d'événements haute importance du NewsManager [{time, impact, currency}]
    
    Returns:
        True = safe to trade | False = trop proche d'une news majeure
    """
    now_utc = datetime.utcnow()
    sym_upper = symbol.upper().replace("/", "")
    
    # --- Filtre dynamique : utiliser les données du NewsManager si disponibles ---
    if news_events:
        for event in news_events:
            impact = event.get('impact', '').upper()
            if impact not in ('HIGH', 'VERY HIGH', '3', '4'):
                continue
            
            event_time = event.get('datetime') or event.get('time')
            if not event_time:
                continue
            
            if isinstance(event_time, str):
                try:
                    event_time = datetime.fromisoformat(event_time.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    continue
            if getattr(event_time, 'tzinfo', None) is not None:
                # Convertir en UTC (ex: ForexFactory publie en -04:00) avant de retirer le fuseau
                event_time = event_time.astimezone(timezone.utc).replace(tzinfo=None)
            
            # Vérifier si la devise de l'événement est dans la paire tradée
            event_currency = event.get('currency', '').upper()
            if event_currency and len(sym_upper) >= 6:
                if event_currency not in (sym_upper[:3], sym_upper[3:6]):
                    continue  # Événement sans rapport avec la paire
            
            time_diff = abs((now_utc - event_time).total_seconds()) / 60.0
            if time_diff <= avoid_minutes:
                log.info(
                    f"🚫 Trade {symbol} rejeté : Publication majeure dans ±{avoid_minutes}min "
                    f"({event.get('name', 'HIGH IMPACT')} — {event_currency}, impact={impact}). "
                    f"Écart actuel : {time_diff:.0f}min."
                )
                return False
    
    # --- Fallback statique : NFP (premier vendredi du mois, 12h30 UTC) ---
    if now_utc.weekday() == 4:  # Vendredi
        nfp_time = now_utc.replace(hour=12, minute=30, second=0, microsecond=0)
        time_diff = abs((now_utc - nfp_time).total_seconds()) / 60.0
        is_first_friday = now_utc.day <= 7
        if is_first_friday and time_diff <= avoid_minutes:
            log.info(
                f"🚫 Trade {symbol} rejeté : NFP probable dans ±{avoid_minutes}min "
                f"(premier vendredi, 12h30 UTC). Écart : {time_diff:.0f}min."
            )
            return False
    
    # --- Fallback statique : FOMC (mercredis, 18h00 UTC) ---
    if now_utc.weekday() == 2:  # Mercredi
        fomc_time = now_utc.replace(hour=18, minute=0, second=0, microsecond=0)
        fomc_diff = abs((now_utc - fomc_time).total_seconds()) / 60.0
        if fomc_diff <= (avoid_minutes // 2):  # Fenêtre réduite (pas tous les mercredis)
            log.info(
                f"⚠️ Trade {symbol} — Possible FOMC proche (mercredi 18h UTC). "
                f"Écart : {fomc_diff:.0f}min. Prudence recommandée."
            )
            # Non bloquant sur fallback statique (risque de faux positifs trop élevé)
    
    return True  # Aucune news majeure détectée


def is_london_session() -> bool:
    """Compatibilité : alias pour vérifier si le marché Forex est ouvert."""
    return is_market_open()
