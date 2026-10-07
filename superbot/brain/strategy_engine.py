"""
NexQuant SuperBot — Strategy Engine Institutionnel & Adaptatif (Forex & Commodities)
=====================================================================================
Orchestration dynamique des 6 stratégies adaptatives de haut niveau :
1. ELDER_TRIPLE_SCREEN     : Système Triple Écran + Impulsion (Dr. Alexander Elder)
2. CHAN_MEAN_REVERSION     : Retour à la moyenne quantitatif OU + Hurst (Dr. Ernest Chan)
3. MURPHY_TREND            : Suivi de tendance multitemporel + Donchian (John J. Murphy)
4. VOLMAN_PRICE_ACTION     : Scalping Price Action 21 EMA & Buildups (Bob Volman)
5. LONDON_BREAKOUT         : Cassure de la boîte asiatique à l'ouverture de Londres
6. INTERMARKET_MOMENTUM    : Consensus de momentum multi-horizons (TSMOM / Murphy)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from superbot.strategy.base_strategy import BaseStrategy, SignalResult
from superbot.strategy.unified_alpha import UnifiedAlphaStrategy
from superbot.strategy.elder_triple_screen import ElderTripleScreenStrategy
from superbot.strategy.chan_mean_reversion import ChanMeanReversionStrategy
from superbot.strategy.murphy_trend import MurphyTrendStrategy
from superbot.strategy.volman_price_action import VolmanPriceActionStrategy
from superbot.strategy.london_breakout import LondonBreakoutStrategy
from superbot.strategy.intermarket_momentum import IntermarketMomentumStrategy

log = logging.getLogger("nexquant.strategy_engine")


class StrategyEngine:
    """
    Moteur de sélection dynamique et exécution des stratégies.
    Intègre UnifiedAlphaStrategy comme stratégie maîtresse combinée.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None, db=None, session_manager=None, online_learner=None, knowledge_feeder=None, **kwargs):
        self.config = config or {}
        self.db = db
        self.session_manager = session_manager
        self.online_learner = online_learner
        self.knowledge_feeder = knowledge_feeder

        # Suite des stratégies (UnifiedAlphaStrategy en maître)
        self.strategies: Dict[str, BaseStrategy] = self._build_strategies(self.config)
        self._strategy_stats: Dict[str, Dict] = {
            name: {"trades": 0, "wins": 0, "total_pnl": 0.0}
            for name in self.strategies
        }
        log.info(f"StrategyEngine MT5 initialisé ({len(self.strategies)} stratégie(s) chargée(s))")

    @staticmethod
    def _build_strategies(config: Dict[str, Any]) -> Dict[str, BaseStrategy]:
        strategies = {
            "UNIFIED_ALPHA": UnifiedAlphaStrategy(config),
            "ELDER_TRIPLE_SCREEN": ElderTripleScreenStrategy(config),
            "CHAN_MEAN_REVERSION": ChanMeanReversionStrategy(config),
            "MURPHY_TREND": MurphyTrendStrategy(config),
            "VOLMAN_PRICE_ACTION": VolmanPriceActionStrategy(config),
            "LONDON_BREAKOUT": LondonBreakoutStrategy(config),
            "INTERMARKET_MOMENTUM": IntermarketMomentumStrategy(config),
        }
        enabled = config.get("ENABLED_STRATEGIES") or []
        if isinstance(enabled, str):
            enabled = [s.strip().upper() for s in enabled.split(",") if s.strip()]
        if not enabled:
            return strategies
        unknown = sorted(set(enabled) - set(strategies))
        if unknown:
            log.error(f"[StrategyEngine] ENABLED_STRATEGIES : noms inconnus ignorés {unknown} "
                      f"(valides : {sorted(strategies)})")
        selected = {name: strat for name, strat in strategies.items() if name in enabled}
        if not selected:
            log.error("[StrategyEngine] Aucune stratégie active après ENABLED_STRATEGIES : aucun trade ne sera pris.")
        else:
            log.info(f"[StrategyEngine] Stratégies actives : {sorted(selected)}")
        return selected

    def configure(self, config: Dict[str, Any]):
        """
        Applique la configuration réelle (.env) aux stratégies. Le moteur est créé avant la
        stratégie de trading, sans config : sans cet appel, chaque stratégie tournait avec ses
        valeurs codées en dur (SL/TP, seuils) au lieu de celles du .env.
        """
        self.config = dict(config or {})
        self.strategies = self._build_strategies(self.config)
        for name in self.strategies:
            self._strategy_stats.setdefault(name, {"trades": 0, "wins": 0, "total_pnl": 0.0})

    def select_best_strategy(self, regime: str, session_name: Optional[str] = None, **kwargs) -> Tuple[str, float]:
        """Sélectionne le nom de la meilleure stratégie pour un régime et une session donnés."""
        candidates = self._get_candidate_strategies(regime, [session_name] if session_name else ["LONDON"])
        if not candidates:
            return ('MURPHY_TREND', 0.5)
            
        best_strat = candidates[0]
        best_score = -1.0
        
        for cand in candidates:
            stats = self._strategy_stats.get(cand, {})
            trades = stats.get("trades", 0)
            wins = stats.get("wins", 0)
            win_rate = wins / trades if trades > 0 else 0.5
            
            score = win_rate
            if trades > 10:
                if win_rate > 0.5:
                    score += 0.2
                elif win_rate < 0.3:
                    score -= 0.2
                    
            if score > best_score:
                best_score = score
                best_strat = cand
                
        confidence = min(max(best_score, 0.1), 1.0)
        return (best_strat, confidence)

    def record_trade_result(self, strategy_name: str, symbol: str, pnl: float, rr: float = 0.0) -> None:
        """Enregistre le résultat d'un trade pour une stratégie."""
        if strategy_name not in self._strategy_stats:
            self._strategy_stats[strategy_name] = {"trades": 0, "wins": 0, "total_pnl": 0.0}
            
        stats = self._strategy_stats[strategy_name]
        stats["trades"] += 1
        if pnl > 0:
            stats["wins"] += 1
        stats["total_pnl"] += pnl
        
        log.debug(f"Résultat trade pour {strategy_name} ({symbol}): PnL={pnl:.2f}, total_pnl={stats['total_pnl']:.2f}")

    @staticmethod
    def effective_score_min(runtime_score_min: Optional[float] = None) -> float:
        """
        Seuil de score appliqué aux signaux : max(SCORE_MIN configuré, valeur runtime), plafonné à 10.

        La valeur runtime (RuntimeConfig : session, adaptation, walk-forward, cloud) ne peut
        donc que rendre le bot PLUS sélectif que le .env, jamais moins. (Auparavant le seuil
        était lu dans os.environ et toutes ces adaptations étaient ignorées.)
        """
        from superbot import config as _cfg
        floor = float(_cfg.SCORE_MIN)
        runtime = float(runtime_score_min) if runtime_score_min is not None else floor
        return min(10.0, max(floor, runtime))

    def evaluate(
        self,
        df: pd.DataFrame,
        symbol: str,
        regime: Any,
        asset_class: str = "forex",
        current_price: float = 0.0,
        pip_size: float = 0.0001,
        active_sessions: Optional[List[str]] = None,
        session_name: Optional[str] = None,
        score_min: Optional[float] = None
    ) -> SignalResult:
        """
        Évalue les données de marché avec la ou les stratégies les plus pertinentes
        selon le régime de marché et la session active.
        Analyse approfondie du marché et sélection dynamique multi-stratégies :
        1. Analyse préalable de la structure et de la tendance (ADX, EMAs, RSI).
        2. Si le régime est chaotique (choppy_noise) : aucun ordre posé pour protéger le capital.
        3. Test séquentiel des stratégies adaptées au régime. Si la première stratégie
           ne déclenche pas, basculement automatique sur les stratégies alternatives.
        4. Validation d'un ratio R:R >= 2.0 pour poser des trades réfléchis et conséquents.
        5. Renseignement exhaustif du 'Pourquoi et Comment' dans decision_rationale.
        """
        if isinstance(regime, str):
            from superbot.brain.regime_detector import RegimeResult
            regime = RegimeResult(regime=regime, confidence=0.8)
        if session_name and not active_sessions:
            active_sessions = [session_name]
        if df is None or len(df) < 20:
            return SignalResult(
                strategy_name="NONE",
                market_regime=regime.regime,
                reason="Données insuffisantes",
                decision_rationale="Données de barres insuffisantes (<20) pour établir une analyse technique fiable."
            )

        active_sessions = active_sessions or ["LONDON"]
        regime_type = regime.regime

        # Déterminer la liste ordonnée des stratégies candidates selon le régime
        regime_normalized = str(regime_type).lower().strip()
        if regime_normalized in ("choppy_noise", "high_volatility"):
            log.info(f"🛡️ [Anti-Noise] {symbol} en régime '{regime_type}' : marché sans tendance ni direction. Ordre évité.")
            return SignalResult(
                strategy_name="NONE",
                market_regime=regime_type,
                reason=f"Régime de marché non-tradable ({regime_type})",
                decision_rationale=(
                    f"Analyse approfondie {symbol} : Le marché est en phase de bruit chaotique ({regime_type} - "
                    f"ADX faible, absence de structure directionnelle). Aucune stratégie engagée pour préserver le capital."
                ),
                should_long=False,
                should_short=False,
                confidence=0.0
            )

        # 2. Liste ordonnée des stratégies candidates selon le régime et la session
        candidates: List[str] = self._get_candidate_strategies(regime_type, active_sessions)
        if not candidates:
            log.info(f"🛡️ [Régime] Aucune stratégie candidate pour {symbol} en régime '{regime_type}'. Pas de trade.")
            return SignalResult(
                strategy_name="NONE",
                market_regime=regime_type,
                reason=f"Aucune stratégie candidate pour le régime {regime_type}",
                decision_rationale=(
                    f"Analyse approfondie {symbol} : Régime {regime_type.upper()} sans stratégie adaptée. "
                    f"Ordre différé pour préserver le capital."
                ),
                should_long=False,
                should_short=False,
                confidence=0.0
            )

        best_signal: Optional[SignalResult] = None
        highest_score = -1.0
        tested_summaries: List[str] = []

        last_row = df.iloc[-1]
        adx_val = float(last_row.get('adx', 20.0))
        rsi_val = float(last_row.get('rsi', 50.0))

        # Adaptations issues du post-mortem (si enchaînement de pertes antérieur)
        adapted_params = None
        if getattr(self, 'performance_learner', None):
            try:
                adapted_params = self.performance_learner.get_symbol_adapted_params(symbol)
            except Exception:
                adapted_params = None

        for strat_name in candidates:
            strat = self.strategies.get(strat_name)
            if not strat:
                continue
            learner = getattr(self, 'performance_learner', None)
            if learner is not None and learner.is_strategy_blocked(strat_name):
                tested_summaries.append(f"{strat_name} (bloquée : win rate < 30 % sur ≥ 10 trades)")
                continue

            try:
                # Une seule analyse par stratégie (l'appel était auparavant doublé, résultat jeté)
                if strat_name == "UNIFIED_ALPHA":
                    sig = strat.analyze(
                        df=df,
                        symbol=symbol,
                        regime=regime,
                        asset_class=asset_class,
                        current_price=current_price,
                        pip_size=pip_size,
                        adapted_params=adapted_params
                    )
                else:
                    sig = strat.analyze(
                        df=df,
                        symbol=symbol,
                        regime=regime,
                        asset_class=asset_class,
                        current_price=current_price,
                        pip_size=pip_size
                    )

                # Vérifier si un signal est généré
                has_signal = sig.should_long or sig.should_short

                if has_signal:
                    # Règle "Score Minimum Global" : rejeter les signaux trop faibles
                    effective_score_min = self.effective_score_min(score_min)
                    if sig.total_score < effective_score_min:
                        tested_summaries.append(
                            f"{strat_name} (signal rejeté: score {sig.total_score:.1f} < {effective_score_min})"
                        )
                        log.debug(f"[StrategyEngine] {symbol} - Signal {strat_name} rejeté car score ({sig.total_score:.1f}) < SCORE_MIN ({effective_score_min})")
                        continue

                    # Règle "Trades Réfléchis & Conséquents" : R:R minimal de 1.8 (cible >= 2.0)
                    if sig.rr_ratio < 1.8 and sig.rr_ratio > 0:
                        tested_summaries.append(
                            f"{strat_name} (signal rejeté: R:R {sig.rr_ratio:.2f} < 1.8)"
                        )
                        log.debug(f"[StrategyEngine] {symbol} - Signal {strat_name} rejeté car R:R ({sig.rr_ratio:.2f}) insuffisant")
                        continue

                    tested_summaries.append(
                        f"{strat_name} (VALIDÉ: score={sig.total_score:.1f}, R:R={sig.rr_ratio:.2f})"
                    )

                    # Sélectionner la stratégie ayant la plus forte conviction
                    if sig.total_score > highest_score:
                        highest_score = sig.total_score
                        best_signal = sig

                else:
                    # Enregistrer pourquoi la stratégie n'a pas validé pour le rapport "Pourquoi et Comment"
                    reason_short = sig.reason or "conditions techniques non alignées"
                    tested_summaries.append(f"{strat_name} (inactif: {reason_short})")

            except Exception as e:
                log.debug(f"Erreur d'analyse stratégie {strat_name} ({symbol}): {e}")
                tested_summaries.append(f"{strat_name} (erreur analyse: {e})")

        # Si un signal de qualité a été validé
        if best_signal is not None:
            side_str = "ACHAT (LONG)" if best_signal.should_long else "VENTE (SHORT)"
            rationale = (
                f"✅ Analyse approfondie validée sur {symbol} | "
                f"Régime : {regime_type.upper()} (Confiance: {regime.confidence:.0%}) | "
                f"Tendance / Momentum : ADX={adx_val:.1f}, RSI={rsi_val:.1f} | "
                f"Stratégie retenue : {best_signal.strategy_name} | "
                f"Décision : {side_str} @ {best_signal.entry_price:.5f} | "
                f"Stop-Loss : {best_signal.sl_price:.5f} | Take-Profit : {best_signal.tp_price:.5f} | "
                f"Ratio R:R : {best_signal.rr_ratio:.2f} | Score : {best_signal.total_score:.1f}/10 | "
                f"Motif : {best_signal.reason} | "
                f"Processus multi-stratégies : {'; '.join(tested_summaries)}"
            )
            best_signal.decision_rationale = rationale
            best_signal.extra_data['tested_strategies'] = tested_summaries
            best_signal.extra_data['market_regime'] = regime_type
            best_signal.extra_data['regime_confidence'] = regime.confidence
            best_signal.extra_data['adx'] = adx_val
            best_signal.extra_data['rsi'] = rsi_val
            return best_signal

        # Si aucune stratégie n'a déclenché de signal à haute probabilité, préserver le capital
        no_signal_rationale = (
            f"🔍 Analyse approfondie {symbol} | Régime : {regime_type.upper()} "
            f"(ADX={adx_val:.1f}, RSI={rsi_val:.1f}) | "
            f"Stratégies évaluées : {'; '.join(tested_summaries)} | "
            f"Conclusion : Aucune configuration à haute probabilité conforme (R:R >= 1.8 ou déclenchement absent). "
            f"Ordre différé pour préserver le capital."
        )
        return SignalResult(
            # Première stratégie candidate réellement active (et non UNIFIED_ALPHA si elle est désactivée)
            strategy_name=next((c for c in candidates if c in self.strategies), "NONE"),
            market_regime=regime_type,
            reason="Aucun setup à haute probabilité conforme après test multi-stratégies",
            decision_rationale=no_signal_rationale,
            should_long=False,
            should_short=False,
            confidence=0.0,
            extra_data={'tested_strategies': tested_summaries, 'adx': adx_val, 'rsi': rsi_val}
        )

    def _get_candidate_strategies(self, regime_type: str, active_sessions: List[str]) -> List[str]:
        """
        Sélectionne les stratégies prioritaires selon le régime et la session.
        UNIFIED_ALPHA est systématiquement la stratégie maîtresse prioritaire.
        Sélectionne UNE stratégie dominante par régime de marché.
        Principe : ne jamais mélanger trend-following et mean-reversion
        sur le même signal pour éviter les conflits directionnels.

        Régime trending   → suivi de tendance uniquement (Elder/Murphy)
        Régime ranging    → retour à la moyenne uniquement (Chan)
        Régime breakout   → cassure uniquement (London Breakout en session)
        Régime choppy/HV  → AUCUN trade (préservation du capital)
        """
        candidates: List[str] = []

        # 1. Tendance forte — uniquement du trend-following
        if regime_type in ["trending_bull", "trending_bear"]:
            candidates = [
                "UNIFIED_ALPHA",
                "ELDER_TRIPLE_SCREEN",
                "MURPHY_TREND",
                "INTERMARKET_MOMENTUM",
                "VOLMAN_PRICE_ACTION"
            ]

        # 2. Range — uniquement du mean-reversion
        elif regime_type == "ranging":
            candidates = [
                "UNIFIED_ALPHA",
                "CHAN_MEAN_REVERSION",
                "VOLMAN_PRICE_ACTION"
            ]

        # 3. Bruit / Choppy et haute volatilité — aucun trade
        elif regime_type in ("choppy_noise", "high_volatility"):
            candidates = []

        # 4. Breakout — London Breakout en session Londres/Overlap uniquement
        #    (hors de ces sessions, pas de breakout fiable : aucun trade)
        elif regime_type in ["pre_breakout", "breakout"]:
            if "LONDON" in active_sessions or "OVERLAP" in active_sessions:
                candidates = [
                    "UNIFIED_ALPHA",
                    "LONDON_BREAKOUT",
                    "VOLMAN_PRICE_ACTION",
                    "MURPHY_TREND"
                ]

        # 5. Défaut (régime inconnu) — stratégie la plus conservatrice
        else:
            candidates = [
                "UNIFIED_ALPHA",
                "MURPHY_TREND",
                "ELDER_TRIPLE_SCREEN",
                "CHAN_MEAN_REVERSION"
            ]

        return candidates

    def get_strategy_leaderboard(self) -> list:
        board = []
        for name in self.strategies:
            stats = self._strategy_stats.get(name, {})
            trades = stats.get("trades", 0)
            wins = stats.get("wins", 0)
            win_rate = wins / trades if trades > 0 else 0.0
            pnl = stats.get("total_pnl", 0.0)
            board.append({
                'name': name,
                'trades': trades,
                'win_rate': win_rate,
                'pnl': pnl
            })
        return sorted(board, key=lambda x: x['pnl'], reverse=True)

