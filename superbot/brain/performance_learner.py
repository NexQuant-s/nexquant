"""
NexQuant V3 — Performance Learner (Auto-apprentissage)
=========================================================
Phase 5 : Le bot apprend de lui-même avant, pendant et après chaque session.

Trois moments d'apprentissage :
  1. PRÉ-SESSION   : Analyse de l'historique → ajuste les paramètres pour la session
  2. MID-SESSION   : Contrôle de performance en cours → ajustements si dérive
  3. POST-SESSION  : Débrief complet → met à jour les profils, stratégies, scores

Mécanismes d'apprentissage :
  - Adaptation du score_min selon le taux de succès récent
  - Adaptation du risk_pct selon le drawdown en cours
  - Blocage automatique des symboles/stratégies perdants
  - Mise à jour des profils de symboles dans la DB
  - Ajustement des multiplicateurs ATR par symbole
  - Calcul du target journalier adaptatif
  - Walk-Forward calibration des paramètres

Logique :
  - Si WinRate < 40% sur 20 trades → +10% score_min (plus sélectif)
  - Si WinRate > 65% sur 20 trades → -5% score_min (moins sélectif, exploiter)
  - Si Daily PnL > 150% target → réduire risk (protéger les gains)
  - Si Daily PnL < -50% target → réduire risk + passer en mode défensif
  - Si symbole -3 pertes consécutives → block 24h
  - Si stratégie < 30% WR sur 10 trades → désactiver 7 jours
"""

import logging
import threading
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("nexquant.performance_learner")


class PerformanceLearner:
    """
    Module d'auto-apprentissage continu.
    
    Intégration avec :
    - NexQuantDB (stockage des apprentissages)
    - SessionManager (objectifs journaliers)
    - StrategyEngine (classement des stratégies)
    - RiskManager (adaptation du risque)
    
    Est appelé :
    - Par le cycle_runner tous les N cycles (_adaptation_every)
    - À la fin de chaque session (SessionManager.tick())
    - Manuellement pour les analyses approfondies
    """

    def __init__(self, db=None, session_manager=None, strategy_engine=None, report_generator=None):
        self._db = db
        self._session_manager = session_manager
        self._strategy_engine = strategy_engine
        self._report_generator = report_generator
        self._lock = threading.RLock()

        # Adaptations spécifiques par symbole (post-mortem 10 min)
        self._symbol_adapted_params: Dict[str, Dict[str, Any]] = {}

        # État courant des paramètres adaptatifs
        self._current_params: Dict[str, Any] = {
            'score_min': 6,
            'risk_pct': 1.0,
            'max_positions': 3,
            'sl_atr_mult': 1.5,
            'tp_atr_mult': 3.0,
        }

        # Statistiques de la session courante
        self._session_trades: List[Dict] = []
        self._session_start_balance: float = 0.0
        self._session_start_time: Optional[datetime] = None

        # Mode défensif (activé en cas de pertes importantes)
        self._defensive_mode: bool = False
        self._defensive_until: Optional[datetime] = None
        self._profit_protection: bool = False  # risque réduit après +150 % de l'objectif du jour

        # Blocages dynamiques (symboles et stratégies)
        self._blocked_strategies: Dict[str, datetime] = {}  # strategy -> blocked_until
        self._symbol_consecutive_losses: Dict[str, Dict] = {}  # symbol -> {'count': int, 'blocked_at': Optional[datetime]}

        log.info("PerformanceLearner V3 initialisé")

    # ─────────────────────────────────────────────────────────────────────────
    # MÉTHODES D'APPRENTISSAGE
    # ─────────────────────────────────────────────────────────────────────────

    def pre_session_analysis(self, bot=None) -> Dict[str, Any]:
        """
        Analyse pré-session : ajuste les paramètres avant de trader.
        Appelé automatiquement à l'ouverture de chaque session (via SessionManager).
        """
        log.info("🔍 [PRÉ-SESSION] Analyse des performances passées...")
        adjustments = {}

        # 1. Récupérer les stats des derniers 20 trades
        stats = self._get_recent_stats(n_trades=20)
        win_rate = float(stats.get('win_rate') or 50)
        avg_rr = float(stats.get('avg_rr') or 2.0)
        total_trades = int(stats.get('total_trades') or 0)

        # 2. Adapter le score_min selon le WinRate (calibré depuis la base 6.0)
        if total_trades >= 10:
            old_score = self._current_params.get('score_min', 6)
            base_score = 6.0
            if win_rate < 35:
                new_score = min(7.0, base_score + 1.0)
                reason = f"WinRate faible ({win_rate:.0f}%) → sélectivité renforcée (score=7.0)"
            elif win_rate < 45:
                new_score = min(6.5, base_score + 0.5)
                reason = f"WinRate modéré ({win_rate:.0f}%) → légère sélectivité (score=6.5)"
            elif win_rate > 65:
                new_score = max(5.5, base_score - 0.5)
                reason = f"WinRate élevé ({win_rate:.0f}%) → opportunisme actif (score=5.5)"
            else:
                new_score = base_score
                reason = "WinRate équilibré (score=6.0)"

            if new_score != old_score:
                self._log_adjustment('score_min', old_score, new_score, reason, 'pre_session')
                self._current_params['score_min'] = new_score
                adjustments['score_min'] = new_score

        # 3. Analyser les meilleurs horaires de session
        best_session = self._get_best_performing_session()
        adjustments['best_session'] = best_session

        # 4. Identifier les symboles problématiques
        blocked_symbols = self._get_blocked_symbols()
        adjustments['blocked_symbols'] = list(blocked_symbols)

        # 5. Vérifier le mode défensif
        if self._defensive_mode and self._defensive_until:
            if datetime.now(timezone.utc) >= self._defensive_until:
                self._defensive_mode = False
                self._defensive_until = None
                log.info("✅ Mode défensif levé")
        adjustments['defensive_mode'] = self._defensive_mode

        # 6. Logger en DB
        if self._db:
            try:
                self._db.insert_knowledge_item({
                    'source_type': 'pre_session_analysis',
                    'title': f"[PRÉ-SESSION] WR={win_rate:.0f}% | score_min={self._current_params['score_min']}",
                    'content': json.dumps({'stats': stats, 'adjustments': adjustments}),
                    'relevance_score': 1.0,
                    'assets_mentioned': [],
                })
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        log.info(
            f"✅ [PRÉ-SESSION] WR={win_rate:.0f}% | avg_RR={avg_rr:.2f} | "
            f"score_min={self._current_params['score_min']} | "
            f"défensif={self._defensive_mode} | "
            f"blocages={len(adjustments.get('blocked_symbols', []))}"
        )
        return adjustments

    def mid_session_check(self, current_pnl: float, target_pnl: float, balance: float) -> Dict[str, Any]:
        """
        Contrôle mi-session : ajustements en temps réel selon la performance.
        Appelé tous les 30 minutes par le cycle_runner.
        """
        actions = {}
        pnl_ratio = current_pnl / target_pnl if target_pnl > 0 else 0

        # Les multiplicateurs sont FIXES (idempotents) : l'ancienne version multipliait le
        # risque à chaque appel (toutes les 30 min), ce qui l'écrasait vers 0.
        # Objectif dépassé → protéger les gains (jusqu'au reset journalier)
        if pnl_ratio >= 1.5:
            if not self._profit_protection:
                self._profit_protection = True
                self._log_adjustment('risk_multiplier', 1.0, self.PROFIT_PROTECTION_MULT,
                                     f"PnL={current_pnl:.0f}€ dépasse 150% target → protection des gains",
                                     'mid_session', balance, current_pnl)
                log.info(f"💰 [MID-SESSION] Objectif dépassé de 150% → risque ×{self.PROFIT_PROTECTION_MULT}")
            actions['action'] = 'REDUCE_RISK_PROFIT_PROTECTION'

        # Pertes importantes → mode défensif (3 h, non prolongé tant qu'il est actif)
        elif pnl_ratio <= -0.5:
            if not self.is_defensive():
                self._defensive_mode = True
                self._defensive_until = datetime.now(timezone.utc) + timedelta(hours=3)
                self._log_adjustment('risk_multiplier', 1.0, self.DEFENSIVE_MULT,
                                     f"PnL={current_pnl:.0f}€ → pertes 50% target → mode défensif",
                                     'mid_session', balance, current_pnl)
                log.warning(f"⚠️ [MID-SESSION] Mode défensif activé 3 h | PnL={current_pnl:.0f}€ | risque ×{self.DEFENSIVE_MULT}")
            actions['action'] = 'DEFENSIVE_MODE_ACTIVATED'
            actions['defensive_until'] = self._defensive_until.isoformat()

        # Performance légèrement en dessous → légère correction
        elif pnl_ratio < 0.3 and len(self._session_trades) >= 5:
            # Vérifier si c'est une mauvaise série ou juste le marché
            recent_wr = sum(1 for t in self._session_trades[-5:] if t.get('pnl', 0) > 0) / 5
            if recent_wr < 0.4:
                old_score = self._current_params.get('score_min', 6)
                new_score = min(9, old_score + 1)
                if new_score != old_score:
                    self._log_adjustment('score_min', old_score, new_score,
                                         f"WR session={recent_wr:.0%} < 40% → plus sélectif", 'mid_session', balance, current_pnl)
                    self._current_params['score_min'] = new_score
                    actions['score_min'] = new_score
                    actions['action'] = 'INCREASE_SELECTIVITY'

        actions['risk_multiplier'] = self.get_risk_multiplier()
        actions['current_params'] = dict(self._current_params)
        return actions

    # Multiplicateurs de risque appliqués au dimensionnement (signal_executor)
    DEFENSIVE_MULT = 0.3
    PROFIT_PROTECTION_MULT = 0.5

    def is_defensive(self) -> bool:
        """Mode défensif actif (expire automatiquement après `_defensive_until`)."""
        if self._defensive_mode and self._defensive_until and datetime.now(timezone.utc) >= self._defensive_until:
            self._defensive_mode = False
            self._defensive_until = None
            log.info("✅ Mode défensif expiré")
        return self._defensive_mode

    def get_risk_multiplier(self) -> float:
        """Multiplicateur de risque courant : 0.3 en mode défensif, 0.5 en protection des gains, sinon 1."""
        if self.is_defensive():
            return self.DEFENSIVE_MULT
        if self._profit_protection:
            return self.PROFIT_PROTECTION_MULT
        return 1.0

    def reset_daily(self):
        """Remise à zéro journalière des protections intra-journée et des trades de session."""
        with self._lock:
            self._defensive_mode = False
            self._defensive_until = None
            self._profit_protection = False
            self._session_trades = []

    def post_session_debrief(self, session_stats: Dict) -> Dict[str, Any]:
        """
        Débrief post-session complet.
        Appelé automatiquement à la fin de chaque session.
        Met à jour les profils, ajuste les stratégies, prépare la suivante.
        """
        log.info("📊 [POST-SESSION] Débrief en cours...")
        insights = {}

        trades = session_stats.get('trades', [])
        pnl_total = session_stats.get('pnl_total', 0)
        target = session_stats.get('pnl_target', 200)
        session_name = session_stats.get('session_name', 'unknown')

        # 1. Calculer les métriques
        if trades:
            wins = [t for t in trades if t.get('pnl', 0) > 0]
            win_rate = len(wins) / len(trades) * 100
            avg_rr = sum(t.get('rr_ratio', 0) for t in trades) / len(trades)
            best_symbol = max(trades, key=lambda t: t.get('pnl', 0)).get('symbol', '') if trades else ''
            worst_symbol = min(trades, key=lambda t: t.get('pnl', 0)).get('symbol', '') if trades else ''

            insights['win_rate'] = round(win_rate, 1)
            insights['avg_rr'] = round(avg_rr, 2)
            insights['best_symbol'] = best_symbol
            insights['worst_symbol'] = worst_symbol
            insights['total_trades'] = len(trades)

            # 2. Mettre à jour les profils de symboles
            self._update_symbol_profiles(trades)

            # 3. Blocage des stratégies sous-performantes. Les résultats sont déjà enregistrés
            # trade par trade dans on_trade_closed() : ne pas les ré-enregistrer (double comptage).
            self._update_strategy_stats(trades)

            # 4. Pertes consécutives : les compteurs sont déjà maintenus par on_trade_closed() ;
            # les rappeler ici doublerait chaque perte (blocage après 2 pertes au lieu de 3).

        # 5. Générer les insights pour la prochaine session
        next_insights = []
        if pnl_total >= target:
            next_insights.append(f"✅ Objectif atteint ({pnl_total:.0f}€/{target:.0f}€)")
        else:
            next_insights.append(f"⚠️ Objectif non atteint ({pnl_total:.0f}€/{target:.0f}€)")

        # 6. Le multiplicateur de risque (défensif / protection) expire seul (3 h) ou au reset journalier
        insights['risk_multiplier'] = self.get_risk_multiplier()
        insights['next_session_insights'] = next_insights

        # 7. Stocker le débrief en DB
        if self._db:
            try:
                self._db.insert_knowledge_item({
                    'source_type': 'post_session_debrief',
                    'title': f"[POST-{session_name}] PnL={pnl_total:.0f}€/{target:.0f}€",
                    'content': json.dumps({**session_stats, 'insights': insights}),
                    'relevance_score': 1.0,
                    'assets_mentioned': [],
                })
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        log.info(
            f"✅ [POST-SESSION] {session_name} | PnL={pnl_total:.0f}€ | "
            f"WR={insights.get('win_rate', 0):.0f}% | "
            f"insights: {'; '.join(next_insights)}"
        )
        return insights

    # ─────────────────────────────────────────────────────────────────────────
    # APPRENTISSAGE PAR TRADE
    # ─────────────────────────────────────────────────────────────────────────

    def on_trade_closed(self, trade: Dict) -> Dict[str, Any]:
        """
        Appelé immédiatement quand un trade est fermé.
        Met à jour les compteurs et déclenche des ajustements si nécessaire.
        """
        with self._lock:
            self._session_trades.append(trade)

        symbol = trade.get('symbol', '')
        pnl = trade.get('pnl', 0)
        strategy = trade.get('strategy_name', 'unknown')
        rr = trade.get('rr_ratio', 0)

        # Mise à jour des pertes consécutives (Seuil: 2 pertes consécutives -> pause 10 min)
        if symbol not in self._symbol_consecutive_losses:
            self._symbol_consecutive_losses[symbol] = {'count': 0, 'blocked_at': None}
            
        if pnl < 0:
            self._symbol_consecutive_losses[symbol]['count'] += 1
            count = self._symbol_consecutive_losses[symbol]['count']
            if count >= 2:
                self._symbol_consecutive_losses[symbol]['blocked_at'] = datetime.now(timezone.utc)
                log.warning(f"🚫 {symbol} : {count} pertes consécutives → pause automatique de 10 min")
                diag = self.diagnose_consecutive_losses(symbol, trade)
                log.warning(
                    f"⏸️ [Pause 10 min] {symbol} : {count} pertes consécutives -> pause ciblée de 10 minutes. "
                    f"Diagnostic : {diag['cause']} | Adaptation : {diag['action']}"
                )
        else:
            self._symbol_consecutive_losses[symbol] = {'count': 0, 'blocked_at': None}  # Reset en cas de gain
            if symbol in self._symbol_adapted_params:
                del self._symbol_adapted_params[symbol]

        # Mise à jour de la stratégie + blocage éventuel des stratégies sous-performantes
        if self._strategy_engine:
            self._strategy_engine.record_trade_result(strategy, symbol, pnl, rr)
            self._update_strategy_stats()

        # Mise à jour DB
        if self._db:
            try:
                self._db.insert_trade(trade)
            except Exception as e:
                log.debug(f"DB insert trade error: {e}")

        return {
            'symbol': symbol,
            'pnl': pnl,
            'consecutive_losses': self._symbol_consecutive_losses.get(symbol, {}).get('count', 0),
            'symbol_blocked': self.is_symbol_blocked(symbol),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # UTILITAIRES INTERNES
    # ─────────────────────────────────────────────────────────────────────────

    def _get_recent_stats(self, n_trades: int = 20) -> Dict[str, Any]:
        """Récupère les stats des N derniers trades depuis la DB."""
        if self._db:
            try:
                stats = self._db.get_performance_stats(days=14)
                return stats
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")
        # Fallback : calcul depuis les trades en mémoire
        trades = self._session_trades[-n_trades:] if self._session_trades else []
        if not trades:
            return {'win_rate': 50, 'avg_rr': 2.0, 'total_trades': 0}
        wins = sum(1 for t in trades if t.get('pnl', 0) > 0)
        return {
            'win_rate': wins / len(trades) * 100,
            'avg_rr': sum(t.get('rr_ratio', 2) for t in trades) / len(trades),
            'total_trades': len(trades),
        }

    def _get_best_performing_session(self) -> str:
        """Détermine la meilleure session selon l'historique DB."""
        if self._db:
            try:
                sessions = self._db.get_recent_sessions(days=14)
                if sessions:
                    best = max(sessions, key=lambda s: s.get('pnl_total') or 0)
                    return best.get('session_name', 'LONDON')
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")
        return 'LONDON'  # Défaut

    def _get_blocked_symbols(self) -> set:
        """Retourne les symboles bloqués (3+ pertes consécutives)."""
        blocked = set()
        for sym in list(self._symbol_consecutive_losses.keys()):
            if self.is_symbol_blocked(sym):
                blocked.add(sym)
        return blocked

    def _update_symbol_profiles(self, trades: List[Dict]):
        """Met à jour les profils de symboles dans la DB."""
        if not self._db:
            return
        symbol_stats: Dict[str, Dict] = {}
        for trade in trades:
            sym = trade.get('symbol', '')
            if not sym:
                continue
            if sym not in symbol_stats:
                symbol_stats[sym] = {'pnl': 0, 'count': 0, 'wins': 0, 'rr_sum': 0}
            symbol_stats[sym]['pnl'] += trade.get('pnl', 0)
            symbol_stats[sym]['count'] += 1
            if trade.get('pnl', 0) > 0:
                symbol_stats[sym]['wins'] += 1
            symbol_stats[sym]['rr_sum'] += trade.get('rr_ratio', 2)

        for sym, stats in symbol_stats.items():
            count = stats['count']
            if count == 0:
                continue
            try:
                self._db.upsert_symbol_profile(sym, {
                    'win_rate': stats['wins'] / count * 100,
                    'avg_rr': stats['rr_sum'] / count,
                    'total_trades': count,
                })
            except Exception as e:
                log.debug(f"Symbol profile update error {sym}: {e}")

    def _update_strategy_stats(self, trades: List[Dict] = None):
        """
        Bloque 7 jours les stratégies sous-performantes (≥ 10 trades et WR < 30 %).
        Les résultats sont enregistrés trade par trade par on_trade_closed() ; `trades` n'est
        plus ré-enregistré ici (il était compté deux fois).
        """
        if not self._strategy_engine:
            return
        leaderboard = self._strategy_engine.get_strategy_leaderboard()
        for stat in leaderboard:
            strat_name = stat['name']
            if stat['trades'] >= 10 and stat['win_rate'] < 0.30:
                if strat_name not in self._blocked_strategies or self._blocked_strategies[strat_name] < datetime.now(timezone.utc):
                    self._blocked_strategies[strat_name] = datetime.now(timezone.utc) + timedelta(days=7)
                    log.warning(f"⛔ Stratégie {strat_name} bloquée pour 7 jours (WinRate {stat['win_rate']:.1%} sur {stat['trades']} trades)")

    def _update_consecutive_losses(self, trades: List[Dict]):
        """
        Reconstruit les compteurs de pertes consécutives depuis une liste de trades.

        ATTENTION : Ne doit Être utilisé que pour reconstruire l'état historique
        (ex: redémarrage du bot), PAS pour les trades en temps réel.
        Pour les trades live, utiliser on_trade_closed() qui maintient les compteurs
        incrémentalement. Appeler cette méthode sur des trades déjà traités par
        on_trade_closed() causerait un double-comptage (BUG-I1).
        """
        for trade in trades:
            sym = trade.get('symbol', '')
            pnl = trade.get('pnl', 0)
            if sym not in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[sym] = {'count': 0, 'blocked_at': None}
                
            if pnl < 0:
                self._symbol_consecutive_losses[sym]['count'] += 1
                if self._symbol_consecutive_losses[sym]['count'] >= 3:
                    self._symbol_consecutive_losses[sym]['blocked_at'] = datetime.now(timezone.utc)
            else:
                self._symbol_consecutive_losses[sym] = {'count': 0, 'blocked_at': None}

    def _log_adjustment(
        self, param: str, old_val: float, new_val: float,
        reason: str, trigger: str = 'auto',
        balance: float = 0, pnl: float = 0
    ):
        """Log un ajustement de paramètre en DB et logs."""
        log.info(f"🔄 Ajustement {param}: {old_val:.3f} → {new_val:.3f} | {reason}")
        if self._db:
            try:
                self._db.log_adaptive_adjustment(
                    param_name=param, old_value=old_val, new_value=new_val,
                    reason=reason, trigger=trigger, balance=balance, pnl_trigger=pnl
                )
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # API PUBLIQUE
    # ─────────────────────────────────────────────────────────────────────────

    def get_current_params(self) -> Dict[str, Any]:
        """Retourne les paramètres adaptatifs courants."""
        return dict(self._current_params)

    def is_strategy_blocked(self, strategy_name: str) -> bool:
        """Vérifie si une stratégie est bloquée."""
        blocked_until = self._blocked_strategies.get(strategy_name)
        if blocked_until:
            return datetime.now(timezone.utc) < blocked_until
        return False

    def is_symbol_blocked(self, symbol: str) -> bool:
        """Vérifie si un symbole est en pause (pause de 10 min pour pertes consécutives)."""
        info = self._symbol_consecutive_losses.get(symbol)
        if not info:
            return False

        blocked_at = info.get('blocked_at')
        if info.get('count', 0) >= 2 and blocked_at:
            if datetime.now(timezone.utc) < blocked_at + timedelta(minutes=10):
                return True
            else:
                # Pause de 10 min expirée, réactivation automatique du trading
                self._symbol_consecutive_losses[symbol] = {'count': 0, 'blocked_at': None}
                log.info(f"▶️ [Fin de pause 10 min] {symbol} réactivé pour le trading avec stratégie adaptée.")

        return False

    def diagnose_consecutive_losses(self, symbol: str, trade: Dict[str, Any], market_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Analyse approfondie des causes de perte sur un actif spécifique lors d'un enchaînement
        de pertes (>= 2 pertes consécutives).
        Diagnostique la cause de perte et adapte immédiatement la stratégie pour cet actif.
        """
        pnl = trade.get('pnl', 0.0)
        entry_price = float(trade.get('entry_price', 0.0) or 0.0)
        exit_price = float(trade.get('exit_price', 0.0) or 0.0)
        atr = float(trade.get('atr', 0.0) or 0.0)

        causes = []
        if pnl < 0:
            causes.append("Stop-Loss atteint")

        # Analyse de la volatilité et du décalage de prix
        if atr > 0 and abs(entry_price - exit_price) > 1.4 * atr:
            causes.append("Mèche de volatilité anormale ou accélération adverse")
        else:
            causes.append("Fausse cassure ou retournement de tendance intraday")

        diagnosis_cause = " | ".join(causes)

        # Adaptation stratégique ciblée sur cet actif pour les prochains trades
        adapted = {
            'score_min_boost': 1.0,     # Exige une conviction supérieure (+1.0 point)
            'sl_atr_mult_boost': 0.2,   # Élargit le Stop-Loss de +20% pour absorber le bruit
            'tp_atr_mult_boost': 0.4,   # Augmente le Take-Profit pour préserver R:R >= 2.2
            'cooldown_minutes': 10,
            'adapted_at': datetime.now(timezone.utc).isoformat()
        }
        self._symbol_adapted_params[symbol] = adapted

        if self._report_generator and hasattr(self._report_generator, 'record_post_mortem_event'):
            try:
                self._report_generator.record_post_mortem_event(
                    symbol=symbol,
                    consecutive_losses=self._symbol_consecutive_losses.get(symbol, {}).get('count', 2),
                    cause=diagnosis_cause,
                    adapted_parameters=adapted,
                    details={'trade': trade}
                )
            except Exception as e:
                log.debug(f"Erreur enregistrement post-mortem dans report_generator: {e}")

        return {
            'symbol': symbol,
            'cause': diagnosis_cause,
            'action': f"Pause 10 min activée. Paramètres adaptés : score requis +{adapted['score_min_boost']}, SL +{adapted['sl_atr_mult_boost']*100:.0f}% ATR.",
            'adapted': adapted
        }

    def get_symbol_adapted_params(self, symbol: str) -> Dict[str, Any]:
        """Retourne les adaptations de paramètres actives pour un symbole."""
        return dict(self._symbol_adapted_params.get(symbol, {}))

    def get_active_pauses(self) -> Dict[str, Dict[str, Any]]:
        """Retourne les symboles actuellement en pause de 10 min suite à des pertes."""
        active = {}
        now = datetime.now(timezone.utc)
        for sym, info in self._symbol_consecutive_losses.items():
            blocked_at = info.get('blocked_at')
            count = info.get('count', 0)
            if count >= 2 and blocked_at:
                remaining = (blocked_at + timedelta(minutes=10) - now).total_seconds()
                if remaining > 0:
                    active[sym] = {
                        'consecutive_losses': count,
                        'blocked_at': blocked_at.strftime('%H:%M UTC'),
                        'remaining_seconds': int(remaining),
                        'remaining_minutes': round(remaining / 60.0, 1)
                    }
        return active

    def get_learning_report(self) -> Dict[str, Any]:
        """Retourne un rapport d'apprentissage complet."""
        stats = self._get_recent_stats(20)
        blocked = list(self._get_blocked_symbols())
        return {
            'current_params': self._current_params,
            'recent_stats': stats,
            'defensive_mode': self._defensive_mode,
            'defensive_until': self._defensive_until.isoformat() if self._defensive_until else None,
            'blocked_symbols': blocked,
            'blocked_strategies': list(self._blocked_strategies.keys()),
            'session_trades_count': len(self._session_trades),
            'strategy_leaderboard': self._strategy_engine.get_strategy_leaderboard() if self._strategy_engine else [],
        }
