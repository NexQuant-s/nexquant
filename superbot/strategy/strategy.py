"""
NexQuant SuperBot — TradingStrategy Adaptative & Institutionnelle (MT5)
========================================================================
Adaptateur de haut niveau connectant le StrategyEngine, le MarketRegimeDetector
et la suite des 6 stratégies d'élite à l'orchestrateur.
"""

from typing import Dict, Any, Optional
import pandas as pd
import logging

from superbot.strategy.base_strategy import SignalResult
from superbot.brain.regime_detector import RegimeResult
from superbot.broker.symbol_specs import get_asset_class, get_pip_size, get_active_sessions

log = logging.getLogger("nexquant.trading_strategy")


class TradingStrategy:
    """
    Stratégie de trading unifiée pour MT5 (Matières Premières & Devises).
    """

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        db=None,
        indicators=None,
        online_learner=None,
        knowledge_feeder=None,
        strategy_engine=None,
        regime_detector=None,
        session_manager=None,
        **kwargs
    ):
        from superbot.brain.strategy_engine import StrategyEngine
        from superbot.brain.regime_detector import MarketRegimeDetector

        self.config = config or {}
        self.db = db
        self.indicators = indicators
        self.online_learner = online_learner
        self.knowledge_feeder = knowledge_feeder
        self.session_manager = session_manager
        self.score_min = int(self.config.get('SCORE_MIN', 6))
        self.risk_per_trade = float(self.config.get('RISK_PCT', 1.0))

        self.regime_detector = regime_detector or MarketRegimeDetector(db=db)
        self.strategy_engine = strategy_engine or StrategyEngine(
            config=self.config,
            db=db,
            session_manager=self.session_manager,
            online_learner=self.online_learner,
            knowledge_feeder=self.knowledge_feeder
        )
        log.info("TradingStrategy MT5 adaptative initialisée avec succès")

    def _calculate_potential_rr(self, latest: pd.Series, current_price: float, sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.0, direction: str = 'long'):
        atr = float(latest.get('atr', 0.0))
        if direction == 'long':
            sl_price = current_price - (sl_atr_mult * atr)
            tp_price = current_price + (tp_atr_mult * atr)
            risk = current_price - sl_price
            reward = tp_price - current_price
        else:
            sl_price = current_price + (sl_atr_mult * atr)
            tp_price = current_price - (tp_atr_mult * atr)
            risk = sl_price - current_price
            reward = current_price - tp_price
            
        rr = reward / risk if risk > 0 else 0.0
        return rr, sl_price, tp_price

    def analyze_market(
        self,
        df: pd.DataFrame,
        account_balance: float = 10000.0,
        real_win_rate: float = 0.5,
        symbol: str = "EURUSD",
        btc_change_24h: Optional[float] = None,
        sentiment_factor: float = 1.0,
        news_filter_passed: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Point d'entrée principal pour l'analyse de marché sur un symbole.
        """
        if df is None or len(df) < 20:
            return {
                "symbol": symbol,
                "should_long": False,
                "should_short": False,
                "trigger_long": False,
                "trigger_short": False,
                "total_score": 0.0,
                "market_regime": "ranging",
                "strategy_used": "NONE",
                "confidence": 0.0,
                "entry_price": 0.0,
                "sl_price": 0.0,
                "tp_price": 0.0,
                "rr_ratio": 0.0,
                "score_min": self.score_min,
                "reason": "Données insuffisantes",
            }

        last = df.iloc[-1]
        current_price = float(last.get('close', 0.0))
        asset_class = get_asset_class(symbol)
        pip_size = get_pip_size(symbol)
        if self.session_manager:
            curr_sess = self.session_manager.get_current_session()
            active_sessions = [curr_sess.get('name', 'LONDON')]
        else:
            # Heure de la dernière bougie (et non l'horloge du PC) : indispensable en backtest
            bar_hour = None
            if isinstance(df.index, pd.DatetimeIndex):
                from superbot.strategy.knowledge_base import utc_bar_times
                bar_hour = utc_bar_times(df)[-1].hour
            active_sessions = get_active_sessions(bar_hour)

        # 1. Détection automatique du régime de marché
        regime: RegimeResult = self.regime_detector.detect(
            df=df,
            symbol=symbol,
            asset_class=asset_class,
            store_in_db=bool(self.db is not None)
        )

        # 2. Évaluation des stratégies adaptatives par le moteur (processus séquentiel approfondi)
        sig: SignalResult = self.strategy_engine.evaluate(
            df=df,
            symbol=symbol,
            regime=regime,
            asset_class=asset_class,
            current_price=current_price,
            pip_size=pip_size,
            active_sessions=active_sessions,
            score_min=self.score_min,
        )

        result_dict = sig.to_dict()
        result_dict["symbol"] = symbol
        result_dict["score_min"] = getattr(sig, 'score_min', None) or self.score_min
        result_dict["strategy_used"] = sig.strategy_name
        result_dict["market_regime"] = regime.regime
        result_dict["brain_regime"] = regime.regime
        result_dict["regime_confidence"] = regime.confidence
        result_dict["hurst_exponent"] = regime.hurst_exponent
        result_dict["half_life_bars"] = regime.half_life
        result_dict["active_sessions"] = active_sessions
        result_dict["decision_rationale"] = sig.decision_rationale

        return result_dict
