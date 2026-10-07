"""
NexQuant V3 — Session Manager
===============================
Phase 2 : Conscience temporelle du bot.

Le SessionManager détecte automatiquement la session de marché active
et adapte les paramètres du bot en conséquence.

Sessions détectées :
  - PRE_LONDON   : 05:00–07:00 UTC (préparation)
  - LONDON       : 07:00–12:00 UTC (haute liquidité)
  - OVERLAP      : 12:00–16:00 UTC (London+NY = meilleure session Forex)
  - NEW_YORK     : 16:00–21:00 UTC
  - ASIA         : 00:00–05:00 UTC (Tokyo)
  - OFF_HOURS    : 21:00–24:00 UTC (faible liquidité)
  - CRYPTO_24H   : Toujours actif pour les crypto CFD (BTCUSD, ETHUSD)

Chaque session a des règles spécifiques :
  - score_min adaptatif (plus exigeant la nuit)
  - max_positions adaptatif
  - instruments prioritaires
  - objectif de PnL partiel (contribution à l'objectif journalier)
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

log = logging.getLogger("nexquant.session_manager")


# ═══════════════════════════════════════════════════════════════════════════════
# DÉFINITION DES SESSIONS
# ═══════════════════════════════════════════════════════════════════════════════

SESSION_DEFINITIONS = {
    "WEEKEND_CRYPTO": {
        "start_utc": 0, "end_utc": 24,
        "description": "Session Weekend Crypto (Marchés Forex & Matières premières fermés, scan & trading exclusif crypto)",
        "liquidity": "high",
        "score_multiplier": 1.0,
        "max_positions_ratio": 1.0,
        "risk_multiplier": 1.0,
        "priority_assets": ["BTCUSD", "ETHUSD", "BNBUSD", "XRPUSD", "SOLUSD"],
        "pnl_target_pct": 0.50,
        "allow_new_trades": True,
    },
    "PRE_LONDON": {
        "start_utc": 5, "end_utc": 7,
        "description": "Pré-London (préparation, momentum pré-ouverture)",
        "liquidity": "medium",
        "score_multiplier": 1.05,     # Légère sélectivité
        "max_positions_ratio": 0.8,   # 80% des positions max
        "risk_multiplier": 0.85,
        "priority_assets": ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "USDJPY", "XAUUSD", "XTIUSD", "XBRUSD"],
        "pnl_target_pct": 0.15,
        "allow_new_trades": True,
    },
    "LONDON": {
        "start_utc": 7, "end_utc": 12,
        "description": "Session London (haute liquidité Forex & Matières Premières)",
        "liquidity": "high",
        "score_multiplier": 1.0,      # Score standard
        "max_positions_ratio": 1.0,   # 100% des positions max
        "risk_multiplier": 1.0,       # Risque standard
        "priority_assets": ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "USDJPY", "XAUUSD", "XTIUSD", "XBRUSD"],
        "pnl_target_pct": 0.40,       # 40% de l'objectif journalier
        "allow_new_trades": True,
    },
    "OVERLAP": {
        "start_utc": 12, "end_utc": 16,
        "description": "London+NY Overlap (pic de liquidité Forex & Matières Premières)",
        "liquidity": "very_high",
        "score_multiplier": 0.95,     # Légèrement plus permissif (très liquide)
        "max_positions_ratio": 1.2,   # +20% positions autorisées
        "risk_multiplier": 1.1,       # Légèrement plus agressif
        "priority_assets": ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "USDJPY", "XAUUSD", "XAGUSD", "XTIUSD", "XBRUSD"],
        "pnl_target_pct": 0.35,       # 35% de l'objectif journalier
        "allow_new_trades": True,
    },
    "NEW_YORK": {
        "start_utc": 16, "end_utc": 21,
        "description": "Session New York (USD dominant & Matières Premières)",
        "liquidity": "high",
        "score_multiplier": 1.0,
        "max_positions_ratio": 1.0,
        "risk_multiplier": 1.0,
        "priority_assets": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "XTIUSD", "XNGUSD"],
        "pnl_target_pct": 0.30,
        "allow_new_trades": True,
    },
    "OFF_HOURS": {
        "start_utc": 21, "end_utc": 24,
        "description": "Heures creuses (faible liquidité Forex)",
        "liquidity": "low",
        "score_multiplier": 1.3,      # +30% score requis
        "max_positions_ratio": 0.4,   # Seulement 40% des positions
        "risk_multiplier": 0.5,       # -50% risque (protection nocturne)
        "priority_assets": ["XAUUSD", "BTCUSD", "ETHUSD"],
        "pnl_target_pct": 0.05,
        "allow_new_trades": True,
    },
    "ASIA": {
        "start_utc": 0, "end_utc": 5,
        "description": "Session Asiatique (Tokyo / JPY / Or)",
        "liquidity": "medium",
        "score_multiplier": 1.15,
        "max_positions_ratio": 0.6,
        "risk_multiplier": 0.8,
        "priority_assets": ["USDJPY", "EURJPY", "XAUUSD"],
        "pnl_target_pct": 0.15,
        "allow_new_trades": True,
    },
}

# Mapping heure / date → nom de session
def _get_session_name_for_datetime(now_utc: Optional[datetime] = None) -> str:
    """Retourne le nom de la session pour une date et heure UTC donnée (gère le weekend)."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    
    from superbot.broker.symbol_specs import is_weekend_market
    if is_weekend_market(now_utc):
        return "WEEKEND_CRYPTO"

    hour = now_utc.hour
    if 5 <= hour < 7:
        return "PRE_LONDON"
    elif 7 <= hour < 12:
        return "LONDON"
    elif 12 <= hour < 16:
        return "OVERLAP"
    elif 16 <= hour < 21:
        return "NEW_YORK"
    elif 21 <= hour < 24:
        return "OFF_HOURS"
    else:  # 0-5
        return "ASIA"


def _get_session_name_for_hour(hour_utc: int) -> str:
    """Retourne le nom de la session pour une heure UTC donnée (fallback)."""
    now_utc = datetime.now(timezone.utc).replace(hour=hour_utc)
    return _get_session_name_for_datetime(now_utc)


class SessionManager:
    """
    Gestionnaire de sessions de trading V3.
    
    Rôles :
    1. Détecter la session active (Asia/London/Overlap/NY/Off)
    2. Adapter les paramètres du bot à la session
    3. Tracker les objectifs partiels de PnL par session
    4. Déclencher les analyses pré/mid/post session
    5. Gérer les transitions de session (reset des compteurs)
    
    Thread-safe via RLock.
    """

    def __init__(self, bot_instance=None, daily_target_eur: float = 200.0):
        self.bot = bot_instance
        self.daily_target_eur = daily_target_eur
        self._lock = threading.RLock()

        # Session courante
        self._current_session_name: str = ""
        self._current_session: Dict = {}
        self._session_started_at: Optional[datetime] = None
        self._session_id: Optional[int] = None

        # Tracking PnL par session
        self._session_pnl: float = 0.0
        self._daily_pnl: float = 0.0
        self._daily_pnl_start: float = 0.0
        self._session_trades: int = 0

        # Historique des transitions
        self._session_history: List[Dict] = []
        self._last_transition_check = datetime.now(timezone.utc)

        # DB (optionnel)
        self._db = None
        try:
            from superbot.db.database import get_db
            self._db = get_db()
        except Exception as _exc:
            log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        # Initialiser la session courante
        self._update_current_session()
        log.info(f"SessionManager V3 initialisé | Session: {self._current_session_name} | Target: {daily_target_eur}€/j")

    # ─────────────────────────────────────────────────────────────────────────
    # DÉTECTION DE SESSION
    # ─────────────────────────────────────────────────────────────────────────

    def _update_current_session(self):
        """Met à jour la session active selon l'heure UTC actuelle et le statut weekend."""
        now_utc = datetime.now(timezone.utc)
        new_session_name = _get_session_name_for_datetime(now_utc)

        with self._lock:
            if new_session_name != self._current_session_name:
                old_name = self._current_session_name
                self._on_session_transition(old_name, new_session_name, now_utc)

    def _on_session_transition(self, old_name: str, new_name: str, timestamp: datetime):
        """Gère la transition entre deux sessions."""
        # Clôturer l'ancienne session
        if old_name and self._session_id:
            self._close_current_session()

        # Démarrer la nouvelle session
        self._current_session_name = new_name
        self._current_session = SESSION_DEFINITIONS.get(new_name, {})
        self._session_started_at = timestamp
        self._session_pnl = 0.0
        self._session_trades = 0

        # Calculer l'objectif de cette session
        session_pct = self._current_session.get('pnl_target_pct', 0.20)
        session_target = self.daily_target_eur * session_pct

        # Enregistrer en DB
        if self._db:
            try:
                self._session_id = self._db.start_session(
                    session_name=new_name,
                    balance_start=self._get_balance(),
                    pnl_target=session_target
                )
            except Exception as e:
                log.debug(f"DB session start error: {e}")
                self._session_id = None

        log.info(
            f"🕐 Transition session : {old_name or 'INIT'} → {new_name} | "
            f"Target session: {session_target:.0f}€ | "
            f"Description: {self._current_session.get('description', '')}"
        )

        # Notifier le bot si disponible
        if self.bot:
            self._apply_session_params_to_bot()

    def _close_current_session(self):
        """Clôture la session courante et enregistre les stats."""
        target = self.daily_target_eur * self._current_session.get('pnl_target_pct', 0.2)
        learner = getattr(self.bot, 'performance_learner', None) if self.bot else None
        if learner is not None:
            # Débrief post-session (profils symboles, blocage de stratégies) — n'était jamais appelé
            try:
                started = self._session_started_at
                trades = [t for t in getattr(learner, '_session_trades', [])
                          if not started or str(t.get('timestamp', '')) >= started.isoformat()]
                learner.post_session_debrief({
                    'trades': trades, 'pnl_total': self._session_pnl,
                    'pnl_target': target, 'session_name': self._current_session_name,
                })
            except Exception as e:
                log.debug(f"Débrief post-session impossible : {e}")
        if not self._session_id or not self._db:
            return
        try:
            target = self.daily_target_eur * self._current_session.get('pnl_target_pct', 0.2)
            self._db.close_session(self._session_id, {
                'balance_end': self._get_balance(),
                'pnl_total': self._session_pnl,
                'pnl_target': target,
                'trades_count': self._session_trades,
                'wins': 0,  # sera mis à jour par le PerformanceLearner
                'losses': 0,
            })
        except Exception as e:
            log.debug(f"DB session close error: {e}")

    def _get_balance(self) -> float:
        """Retourne le solde courant depuis le bot."""
        if self.bot:
            return getattr(self.bot, '_cached_balance', 0.0) or getattr(self.bot, 'initial_balance', 0.0)
        return 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # API PUBLIQUE
    # ─────────────────────────────────────────────────────────────────────────
    
    def reset_daily(self, balance_start: float = 0.0):
        """
        Reset journalier — appelé à minuit UTC.

        BUG-A01 FIX: Il y avait deux définitions de reset_daily() (L251 et L356).
        La seconde écrasait la première silencieusement en Python. Cette version
        unique combine les deux comportements : reset des compteurs de session
        ET mise à jour de daily_target_eur via _compute_daily_target().
        """
        with self._lock:
            # Reset PnL et compteurs (ancienne version L356)
            self._daily_pnl_start = balance_start
            self._daily_pnl = 0.0
            self._session_pnl = 0.0
            self._session_trades = 0

            # Recalculer l'objectif journalier (ancienne version L251)
            self.daily_target_eur = self._compute_daily_target(balance_start)

        if self._db:
            try:
                self._db.set_daily_target(balance_start, self.daily_target_eur)
            except Exception as e:
                log.debug(f"Erreur DB set_daily_target: {e}")

        log.info(
            f"📅 Reset journalier | Solde={balance_start:.2f}€ | "
            f"Target={self.daily_target_eur:.2f}€ | Session PnL reseté"
        )



    def tick(self):
        """
        Appelé à chaque cycle de trading.
        Vérifie si une transition de session doit être effectuée.
        """
        now = datetime.now(timezone.utc)
        # Vérifier toutes les minutes
        if (now - self._last_transition_check).total_seconds() >= 60:
            self._update_current_session()
            self._last_transition_check = now

    def get_current_session(self) -> Dict[str, Any]:
        """Retourne les informations de la session courante."""
        with self._lock:
            return {
                'name': self._current_session_name,
                'description': self._current_session.get('description', ''),
                'liquidity': self._current_session.get('liquidity', 'medium'),
                'score_multiplier': self._current_session.get('score_multiplier', 1.0),
                'max_positions_ratio': self._current_session.get('max_positions_ratio', 1.0),
                'risk_multiplier': self._current_session.get('risk_multiplier', 1.0),
                'priority_assets': self._current_session.get('priority_assets', []),
                'allow_new_trades': self._current_session.get('allow_new_trades', True),
                'pnl_session': round(self._session_pnl, 2),
                'pnl_daily': round(self._daily_pnl, 2),
                'trades_count': self._session_trades,
                'started_at': self._session_started_at.isoformat() if self._session_started_at else None,
            }

    def get_adapted_score_min(self, base_score_min: int) -> int:
        """Retourne le score_min adapté à la session courante."""
        multiplier = self._current_session.get('score_multiplier', 1.0)
        return max(base_score_min, int(round(base_score_min * multiplier)))

    def get_adapted_risk_pct(self, base_risk_pct: float) -> float:
        """Retourne le risk_pct adapté à la session courante."""
        multiplier = self._current_session.get('risk_multiplier', 1.0)
        return round(base_risk_pct * multiplier, 3)

    def get_adapted_max_positions(self, base_max: int) -> int:
        """Retourne le max_positions adapté à la session courante."""
        ratio = self._current_session.get('max_positions_ratio', 1.0)
        return max(1, int(round(base_max * ratio)))

    def is_priority_asset(self, symbol: str) -> bool:
        """Retourne True si le symbole est prioritaire dans la session courante."""
        priority = self._current_session.get('priority_assets', [])
        if not priority:
            return True  # Tous prioritaires si non défini
        # Vérification partielle (ex: "EURUSD" dans la liste ou via le base du symbole)
        sym_clean = symbol.upper().replace('/', '').replace('-', '')
        return any(p.replace('/', '').replace('-', '') in sym_clean or sym_clean.startswith(p[:3])
                   for p in priority)

    def can_trade_symbol(self, symbol: str) -> Tuple[bool, str]:
        """
        Vérifie si un symbole peut être tradé dans la session courante.
        Retourne (peut_trader, raison).
        """
        if not self._current_session.get('allow_new_trades', True):
            return False, f"Session {self._current_session_name} : nouveaux trades désactivés"

        # Vérification OFF_HOURS : seulement crypto
        from superbot.broker.symbol_specs import normalize_symbol_name, get_asset_class
        norm = normalize_symbol_name(symbol)
        asset_class = get_asset_class(symbol)
        is_crypto = (asset_class == "crypto")
        is_commodity = asset_class.startswith("commodity")
        allowed_majors = {"EURUSD", "GBPUSD", "EURGBP", "EURJPY", "USDJPY"}
        is_allowed_forex = norm in allowed_majors

        # 1. En Session WEEKEND_CRYPTO : STRICTEMENT CRYPTO
        if self._current_session_name == "WEEKEND_CRYPTO":
            if not is_crypto:
                return False, f"Weekend : Marchés traditionnels fermés. Scan & trading réservés aux cryptos (pas {symbol})"
            return True, "OK (Crypto Weekend)"

        # 2. En Semaine : Interdiction de la crypto (réservée au weekend) et devises hors 5 majeures
        if is_crypto:
            return False, "Crypto réservée au week-end (en semaine, focus matières premières et 5 majeures FX)"
        if not (is_commodity or is_allowed_forex):
            return False, f"{symbol} non autorisé : le bot surveille uniquement les matières premières et EURUSD, GBPUSD, EURGBP, EURJPY, USDJPY en semaine."

        # 3. Vérification OFF_HOURS nocturne (faible liquidité)
        if self._current_session_name == "OFF_HOURS":
            # Matières premières autorisées (l'ancien test comparait la classe à 'commodity' alors
            # que get_asset_class renvoie 'commodity_gold'… : l'or était refusé à tort), sauf
            # pendant le rollover interbancaire (21h55-23h05 UTC) où les spreads explosent.
            from superbot.broker.symbol_specs import is_rollover_period
            if is_rollover_period():
                return False, f"OFF_HOURS : rollover interbancaire (21h55-23h05 UTC), pas de nouveau trade sur {symbol}"
            if not (is_commodity or norm in ("XAUUSD", "GOLD")):
                return False, f"OFF_HOURS : liquidité réduite, seules matières premières autorisées (pas {symbol})"

        return True, "OK"

    def register_trade(self, pnl: float):
        """Enregistre un trade dans les compteurs de session."""
        with self._lock:
            self._session_pnl += pnl
            self._daily_pnl += pnl
            self._session_trades += 1

        # Mise à jour DB
        if self._db:
            try:
                self._db.update_daily_achievement(self._daily_pnl)
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        log.info(
            f"📈 Trade enregistré : PnL={pnl:+.2f}€ | "
            f"Session total={self._session_pnl:+.2f}€ | "
            f"Daily={self._daily_pnl:+.2f}€"
        )


    def _compute_daily_target(self, balance: float) -> float:
        """
        Objectif journalier = DAILY_TARGET_PCT % du solde (2 % par défaut).

        L'ancien barème fixe (200€ dès 1000€, 100€ dès 500€) représentait 10 à 20 %
        du compte par jour : irréaliste avec 1 % de risque par trade et trompeur dans
        les rapports et le suivi d'avancement.
        """
        from superbot.config import DAILY_TARGET_PCT
        return round(max(balance, 0.0) * DAILY_TARGET_PCT / 100.0, 2)

    def get_daily_progress(self) -> Dict[str, Any]:
        """Retourne l'avancement vers l'objectif journalier."""
        target = self.daily_target_eur
        achieved = self._daily_pnl
        pct = (achieved / target * 100) if target > 0 else 0
        return {
            'target_eur': target,
            'achieved_eur': round(achieved, 2),
            'achievement_pct': round(pct, 1),
            'remaining_eur': round(max(0, target - achieved), 2),
            'status': 'achieved' if achieved >= target else ('on_track' if pct >= 50 else 'behind'),
        }

    def _apply_session_params_to_bot(self):
        """
        Applique les paramètres de session au bot (si disponible).

        BUG-A14 FIX: Cette méthode ne faisait que logger les paramètres sans les appliquer.
        Les multiplicateurs de session (risk_multiplier, score_multiplier) sont maintenant
        effectivement propagés au RiskManager et à la stratégie.
        """
        if not self.bot:
            return
        try:
            session = self._current_session
            risk_mult = session.get('risk_multiplier', 1.0)
            pos_ratio = session.get('max_positions_ratio', 1.0)

            score_mult = session.get('score_multiplier', 1.0)
            adapted_score = None
            rc = getattr(self.bot, 'runtime_config', None)
            if rc is not None:
                # Source unique : RuntimeConfig applique le multiplicateur de risque et le décalage
                # de score (auparavant écrits ici directement puis écrasés par RuntimeConfig.apply).
                base_score = rc.score_min
                adapted_score = max(base_score, int(round(base_score * score_mult)))
                rc.set_session_multipliers(risk_multiplier=risk_mult, score_offset=adapted_score - base_score)

            if hasattr(self.bot, 'risk_manager') and self.bot.risk_manager:
                rm = self.bot.risk_manager
                if rc is None:
                    # Repli (bots simulés sans RuntimeConfig)
                    if not hasattr(rm, '_base_risk_pct'):
                        rm._base_risk_pct = rm.RISK_PCT
                    rm.RISK_PCT = round(rm._base_risk_pct * risk_mult, 3)

                # Adapter MAX_OPEN_POSITIONS selon la session
                base_max = getattr(rm, '_base_max_positions', rm.MAX_OPEN_POSITIONS)
                if not hasattr(rm, '_base_max_positions'):
                    rm._base_max_positions = base_max
                rm.MAX_OPEN_POSITIONS = max(3, int(round(base_max * pos_ratio)))

            # Repli : adapter directement le score_min de la stratégie (bots simulés sans RuntimeConfig)
            if rc is None and hasattr(self.bot, 'strategy') and self.bot.strategy:
                strat = self.bot.strategy
                base_score = getattr(strat, '_base_score_min', getattr(strat, 'score_min', 6))
                if not hasattr(strat, '_base_score_min'):
                    strat._base_score_min = getattr(strat, 'score_min', 6)
                adapted_score = max(base_score, int(round(base_score * score_mult)))
                strat.score_min = adapted_score

            log.info(
                f"🎯 Paramètres session {self._current_session_name} appliqués : "
                f"score_min={adapted_score} | risk×{risk_mult:.1f} | positions×{pos_ratio:.1f}"
            )
        except Exception as e:
            log.debug(f"Erreur apply session params : {e}")


    def get_session_summary(self) -> str:
        """Retourne un résumé textuel de la session pour les logs."""
        s = self.get_current_session()
        progress = self.get_daily_progress()
        return (
            f"Session={s['name']} ({s['liquidity']}) | "
            f"PnL session={s['pnl_session']:+.2f}€ | "
            f"Daily={progress['achieved_eur']:+.2f}€/{progress['target_eur']:.0f}€ "
            f"({progress['achievement_pct']:.0f}%) | "
            f"Trades={s['trades_count']}"
        )
