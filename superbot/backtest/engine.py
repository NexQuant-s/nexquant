"""
NexQuant BacktestEngine — Phase 1
===================================
Moteur de simulation de trading sur données historiques réelles.

Fonctionnalités :
  - Simulation SL/TP basée sur les prix High/Low des bougies
  - Coûts de transaction configurables (spread + commission)
  - Gestion du Break-Even automatique (si configuré)
  - Métriques professionnelles : Sharpe, Sortino, Calmar, Profit Factor, Max Drawdown
  - Mode Walk-Forward : division 70% in-sample / 30% out-of-sample
  - Journal complet des trades pour analyse approfondie

Usage :
    config = {'SCORE_MIN': 6, 'RISK_PCT': 1.0, 'SL_ATR_MULT': 1.5, 'TP_ATR_MULT': 3.0}
    strategy = TradingStrategy(config)
    engine = BacktestEngine(df, config)
    results = engine.run(strategy)
    print(results.summary())

    # Mode Walk-Forward
    in_sample, out_sample = engine.run_walk_forward(strategy, train_ratio=0.7)
"""
import math
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("backtest.engine")


@dataclass
class Trade:
    """Représente un trade simulé."""
    entry_time: datetime
    exit_time: Optional[datetime]
    direction: str          # 'LONG' ou 'SHORT'
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    position_size: float    # En unités de base
    pnl: float              # PnL brut en devise de compte
    pnl_pct: float          # PnL en % du capital au moment de l'entrée
    result: str             # 'TP' | 'SL' | 'BREAK_EVEN' | 'TRAILING' | 'CLOSE_END'
    score: float            # Score de la stratégie au moment de l'entrée
    market_regime: str      # Régime de marché détecté
    commission: float       # Coûts de transaction payés
    entry_details: Dict[str, Any] = field(default_factory=dict)  # Votes du score à l'entrée

    def is_winner(self) -> bool:
        return self.pnl > 0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['entry_time'] = self.entry_time.isoformat() if self.entry_time else None
        d['exit_time'] = self.exit_time.isoformat() if self.exit_time else None
        return d


@dataclass
class BacktestResults:
    """Résultats complets d'un backtest."""
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    broker_type: str = 'unknown'

    # Métriques de performance
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    max_drawdown_duration_bars: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    profit_factor: float = 0.0

    # Métriques de trading
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win_pct: float = 0.0
    avg_loss_pct: float = 0.0
    avg_rr_realized: float = 0.0
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    avg_trade_duration_bars: float = 0.0

    # Courbe d'équité et journal
    equity_curve: List[float] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    params_used: Dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        """Retourne un résumé formaté en tableau ASCII."""
        sep = "=" * 60
        lines = [
            sep,
            f"  BACKTEST : {self.symbol} {self.timeframe}",
            f"  Periode  : {self.start_date} -> {self.end_date}",
            sep,
            f"  Capital initial       : ${self.initial_balance:,.2f}",
            f"  Capital final         : ${self.final_balance:,.2f}",
            f"  Rendement total       : {self.total_return_pct:+.2f}%",
            f"  Drawdown max          : {self.max_drawdown_pct:.2f}%  ({self.max_drawdown_duration_bars} bougies)",
            sep,
            f"  Ratio de Sharpe       : {self.sharpe_ratio:.3f}",
            f"  Ratio de Sortino      : {self.sortino_ratio:.3f}",
            f"  Ratio de Calmar       : {self.calmar_ratio:.3f}",
            f"  Profit Factor         : {self.profit_factor:.2f}",
            sep,
            f"  Trades total          : {self.total_trades}",
            f"  Trades gagnants       : {self.winning_trades}  ({self.win_rate*100:.1f}%)",
            f"  Trades perdants       : {self.losing_trades}",
            f"  Gain moyen            : +{self.avg_win_pct:.2f}%",
            f"  Perte moyenne         : {self.avg_loss_pct:.2f}%",
            f"  Meilleur trade        : +{self.best_trade_pct:.2f}%",
            f"  Pire trade            : {self.worst_trade_pct:.2f}%",
            f"  Durée moy. trade      : {self.avg_trade_duration_bars:.0f} bougies",
            sep,
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise les résultats en dictionnaire JSON-compatible."""
        d = asdict(self)
        d['trades'] = [t.to_dict() for t in self.trades]
        return d


class BacktestEngine:
    """
    Moteur de simulation de trading réaliste sur données OHLCV historiques.
    """

    # Coûts par défaut (commission % par côté, spread/slippage %) selon la classe d'actif.
    # Forex (mt5) : commission faible mais spread réel non négligeable.
    # Crypto (binance) : taker ~0.04%, slippage ~0.01%.
    # Actions/ETF (alpaca) : commission ~0, spread serré.
    _COST_DEFAULTS = {
        'binance':  (0.04, 0.01),
        'mt5':      (0.01, 0.02),
        'alpaca':   (0.02, 0.01),
        'yfinance': (0.04, 0.01),
    }

    def __init__(
        self,
        df: pd.DataFrame,
        config: Dict[str, Any],
        initial_balance: float = 10_000.0,
        commission_pct: Optional[float] = None,  # % par côté ; défaut selon broker_type
        spread_pct: Optional[float] = None,       # % spread/slippage additionnel simulé
        symbol: str = 'UNKNOWN',
        timeframe: str = '1h',
        broker_type: str = 'unknown',
    ):
        """
        Args:
            df             : DataFrame OHLCV complet (index DatetimeIndex)
            config         : Configuration de la stratégie (SCORE_MIN, RISK_PCT, etc.)
            initial_balance: Capital de départ en USD
            commission_pct : Commission par trade en % (appliquer à l'entrée ET à la sortie).
                             None = valeur par défaut selon broker_type.
            spread_pct     : Spread additionnel simulé en %.
                             None = valeur par défaut selon broker_type.
            symbol         : Nom de l'instrument (pour les rapports)
            timeframe      : Intervalle de temps (pour les rapports)
            broker_type    : Type de broker utilisé (pour les rapports)
        """
        self.df = df.copy()
        self.config = config
        self.initial_balance = initial_balance

        broker = (broker_type or 'unknown').lower()
        default_comm, default_spread = self._COST_DEFAULTS.get(broker, (0.04, 0.01))
        if commission_pct is None:
            commission_pct = default_comm
        if spread_pct is None:
            spread_pct = default_spread

        self.commission_pct = commission_pct / 100.0
        self.spread_pct = spread_pct / 100.0
        # Tampon de coût pour le break-even : couvre l'aller-retour (commission
        # ×2) + spread, pour qu'une sortie BE soit au moins nulle. En live, le SL
        # est déplacé à entry × 1.0005 (couvre les frais) — on reproduit cela ici
        # au lieu de remonter le SL exactement à l'entrée (qui comptait le BE en
        # perte à cause de la commission).
        self.be_cost_buffer = 2 * self.commission_pct + self.spread_pct

        self.symbol = symbol
        self.timeframe = timeframe
        self.broker_type = broker_type

        # Paramètres de la stratégie
        self.sl_atr_mult = config.get('SL_ATR_MULT', 1.5)
        self.tp_atr_mult = config.get('TP_ATR_MULT', 3.0)
        self.risk_pct = config.get('RISK_PCT', 1.0) / 100.0
        self.be_enabled = config.get('BE_DYN_RR', True)  # Break-even
        self.be_rr_ratio = config.get('BE_DYN_RR_RATIO', 1.5)  # R:R de déclenchement du BE
        self.trail_atr_mult = config.get('TRAIL_ATR_MULT', 1.5)  # Distance du trailing (×ATR)
        self.trail_activate_atr = config.get('TRAIL_ACTIVATE_ATR_MULT', 2.0)  # Activation trailing (×ATR)

    def run(self, strategy, warmup_bars: int = 50) -> BacktestResults:
        """
        Lance le backtest complet sur toutes les données.

        Args:
            strategy    : Instance de TradingStrategy
            warmup_bars : Nombre de bougies initiales à ignorer (calcul des indicateurs)

        Returns:
            BacktestResults avec toutes les métriques calculées
        """
        log.info(f"[BacktestEngine] Démarrage : {self.symbol} | {len(self.df)} bougies | warmup={warmup_bars}")

        # Pré-calculer tous les indicateurs une seule fois.
        # Sûr (sans look-ahead) uniquement parce que les indicateurs utilisés par la
        # stratégie sont CAUSALS (rolling/ewm sur le passé). Le seul indicateur
        # non-causal historique (Ichimoku chikou = close.shift(-26)) a été corrigé
        # en causale dans knowledge_base.calculate_ichimoku.
        df_full = strategy.indicators.calculate_all_indicators(self.df.copy())

        # Override de calculate_all_indicators pour éviter le recalcul à chaque bougie.
        # Chaque tranche df_slice récupère les valeurs déjà calculées (fenêtre passée).
        original_calc = strategy.indicators.calculate_all_indicators
        strategy.indicators.calculate_all_indicators = lambda df_slice: df_full.loc[df_slice.index]

        trades, equity_curve = self._simulate(df_full, strategy, warmup_bars)

        # Restaurer la méthode originale
        strategy.indicators.calculate_all_indicators = original_calc

        return self._compute_results(trades, equity_curve)

    def run_walk_forward(
        self,
        strategy,
        train_ratio: float = 0.7,
        warmup_bars: int = 50,
    ) -> Tuple[BacktestResults, BacktestResults]:
        """
        Découpe les données en segment In-Sample (entraînement) et Out-of-Sample (validation).
        Retourne deux BacktestResults distincts pour comparer les performances.

        Args:
            strategy    : Instance de TradingStrategy
            train_ratio : Fraction des données pour l'In-Sample (défaut: 70%)
            warmup_bars : Bougies initiales ignorées

        Returns:
            Tuple (in_sample_results, out_of_sample_results)
        """
        split_idx = int(len(self.df) * train_ratio)
        df_train = self.df.iloc[:split_idx]
        df_test = self.df.iloc[split_idx:]

        log.info(
            f"[BacktestEngine] Walk-Forward — "
            f"In-Sample: {len(df_train)} bougies ({df_train.index[0].date()} → {df_train.index[-1].date()}) | "
            f"Out-of-Sample: {len(df_test)} bougies ({df_test.index[0].date()} → {df_test.index[-1].date()})"
        )

        engine_train = BacktestEngine(df_train, self.config, self.initial_balance,
                                      symbol=self.symbol, timeframe=self.timeframe)
        engine_test = BacktestEngine(df_test, self.config, self.initial_balance,
                                     symbol=self.symbol, timeframe=self.timeframe)

        in_sample = engine_train.run(strategy, warmup_bars)
        out_sample = engine_test.run(strategy, warmup_bars)

        return in_sample, out_sample

    # ─── Simulation interne ───────────────────────────────────────────────────

    def _simulate(
        self,
        df_full: pd.DataFrame,
        strategy,
        warmup_bars: int,
    ) -> Tuple[List[Trade], List[float]]:
        """Boucle de simulation principale."""

        balance = self.initial_balance
        position: Optional[str] = None    # None | 'LONG' | 'SHORT'
        entry_price = 0.0
        entry_time = None
        entry_bar_idx = 0
        sl = 0.0
        tp = 0.0
        initial_risk = 0.0
        be_triggered = False
        trail_triggered = False
        position_size = 0.0
        entry_score = 0.0
        entry_regime = 'UNKNOWN'
        entry_details: Dict[str, Any] = {}

        trades: List[Trade] = []
        equity_curve: List[float] = [self.initial_balance]

        for i in range(warmup_bars, len(df_full)):
            bar = df_full.iloc[i]
            current_price = bar['close']

            # Mise à jour de l'équité flottante
            if position == 'LONG':
                float_equity = balance + position_size * (current_price - entry_price)
            elif position == 'SHORT':
                float_equity = balance + position_size * (entry_price - current_price)
            else:
                float_equity = balance
            equity_curve.append(float_equity)

            # ── Gestion Break-Even (déplacer SL à l'entrée au R:R configuré) ──
            # Le SL est placé légèrement au-delà de l'entrée (be_cost_buffer) pour
            # couvrir les frais : une sortie BE est alors un petit gain, pas une perte.
            if self.be_enabled and position is not None and not be_triggered and initial_risk > 0:
                if position == 'LONG' and current_price >= entry_price + initial_risk * self.be_rr_ratio:
                    sl = entry_price * (1 + self.be_cost_buffer)
                    be_triggered = True
                    log.debug(f"[BE] LONG Break-Even déclenché à {current_price:.4f} (SL={sl:.4f})")
                elif position == 'SHORT' and current_price <= entry_price - initial_risk * self.be_rr_ratio:
                    sl = entry_price * (1 - self.be_cost_buffer)
                    be_triggered = True
                    log.debug(f"[BE] SHORT Break-Even déclenché à {current_price:.4f} (SL={sl:.4f})")

            # ── Trailing stop (activation à TRAIL_ACTIVATE_ATR_MULT × ATR) ────
            if position is not None and self.trail_atr_mult > 0:
                atr_val = bar.get('atr', 0)
                if atr_val and atr_val > 0:
                    if position == 'LONG':
                        favorable = bar['high'] - entry_price
                        if favorable >= self.trail_activate_atr * atr_val:
                            new_sl = bar['high'] - self.trail_atr_mult * atr_val
                            if new_sl > sl:
                                sl = new_sl
                                trail_triggered = True
                                log.debug(f"[TRAIL] LONG SL -> {sl:.4f}")
                    else:  # SHORT
                        favorable = entry_price - bar['low']
                        if favorable >= self.trail_activate_atr * atr_val:
                            new_sl = bar['low'] + self.trail_atr_mult * atr_val
                            if new_sl < sl:
                                sl = new_sl
                                trail_triggered = True
                                log.debug(f"[TRAIL] SHORT SL -> {sl:.4f}")

            # ── Vérification sortie SL/TP ─────────────────────────────────────
            # Ordre intra-bougie EXPLICITE : si SL et TP sont touchés dans la même
            # bougie, on suppose le pire cas (SL en premier) — convention prudente.
            if position == 'LONG':
                hit_sl = bar['low'] <= sl
                hit_tp = bar['high'] >= tp
                if hit_sl or hit_tp:
                    exit_price = sl if hit_sl else tp
                    if hit_tp and not hit_sl:  # SL+TP dans la même bougie : sortie au SL (pire cas)
                        result_type = 'TP'
                    elif be_triggered:
                        result_type = 'BREAK_EVEN'
                    elif trail_triggered:
                        result_type = 'TRAILING'
                    else:
                        result_type = 'SL'
                    trade = self._close_trade(
                        direction='LONG', entry_price=entry_price, exit_price=exit_price,
                        sl=sl, tp=tp, position_size=position_size,
                        entry_time=entry_time, exit_time=bar.name,
                        balance=balance, result=result_type,
                        score=entry_score, regime=entry_regime, details=entry_details,
                        entry_bar=entry_bar_idx, exit_bar=i,
                    )
                    balance += trade.pnl - trade.commission
                    trades.append(trade)
                    position = None
                    be_triggered = False

            elif position == 'SHORT':
                hit_sl = bar['high'] >= sl
                hit_tp = bar['low'] <= tp
                if hit_sl or hit_tp:
                    exit_price = sl if hit_sl else tp
                    if hit_tp and not hit_sl:  # SL+TP dans la même bougie : sortie au SL (pire cas)
                        result_type = 'TP'
                    elif be_triggered:
                        result_type = 'BREAK_EVEN'
                    elif trail_triggered:
                        result_type = 'TRAILING'
                    else:
                        result_type = 'SL'
                    trade = self._close_trade(
                        direction='SHORT', entry_price=entry_price, exit_price=exit_price,
                        sl=sl, tp=tp, position_size=position_size,
                        entry_time=entry_time, exit_time=bar.name,
                        balance=balance, result=result_type,
                        score=entry_score, regime=entry_regime, details=entry_details,
                        entry_bar=entry_bar_idx, exit_bar=i,
                    )
                    balance += trade.pnl - trade.commission
                    trades.append(trade)
                    position = None
                    be_triggered = False

            # ── Signal d'entrée (uniquement si pas de position ouverte) ────────
            if position is None:
                # df_full (avec indicateurs), comme en live : self.df ne contient que l'OHLCV brut,
                # ce qui privait toutes les stratégies d'ADX/EMA/Bollinger (régimes faux, aucune tendance)
                historical_slice = df_full.iloc[:i + 1]
                try:
                    signal = strategy.analyze_market(historical_slice, account_balance=balance)
                except Exception as e:
                    log.debug(f"[BacktestEngine] Erreur signal barre {i}: {e}")
                    continue

                atr = bar.get('atr', 0)
                if atr == 0:
                    continue

                if signal.get('should_long'):
                    entry_price = current_price * (1 + self.spread_pct / 2)
                    sl = signal['sl_price'] if signal['sl_price'] > 0 else entry_price - atr * self.sl_atr_mult
                    tp = signal['tp_price'] if signal['tp_price'] > 0 else entry_price + atr * self.tp_atr_mult
                    risk_per_unit = abs(entry_price - sl)
                    if risk_per_unit > 0:
                        risk_amount = balance * self.risk_pct
                        position_size = risk_amount / risk_per_unit
                        position = 'LONG'
                        entry_time = bar.name
                        entry_bar_idx = i
                        initial_risk = risk_per_unit
                        be_triggered = False
                        trail_triggered = False
                        entry_score = signal.get('total_score', 0)
                        entry_regime = signal.get('market_regime', 'UNKNOWN')
                        entry_details = signal.get('details', {}) or {}

                elif signal.get('should_short'):
                    entry_price = current_price * (1 - self.spread_pct / 2)
                    sl = signal['sl_price'] if signal['sl_price'] > 0 else entry_price + atr * self.sl_atr_mult
                    tp = signal['tp_price'] if signal['tp_price'] > 0 else entry_price - atr * self.tp_atr_mult
                    risk_per_unit = abs(sl - entry_price)
                    if risk_per_unit > 0:
                        risk_amount = balance * self.risk_pct
                        position_size = risk_amount / risk_per_unit
                        position = 'SHORT'
                        entry_time = bar.name
                        entry_bar_idx = i
                        initial_risk = risk_per_unit
                        be_triggered = False
                        trail_triggered = False
                        entry_score = signal.get('total_score', 0)
                        entry_regime = signal.get('market_regime', 'UNKNOWN')
                        entry_details = signal.get('details', {}) or {}

        # Fermer la position ouverte à la fin du backtest
        if position is not None:
            final_bar = df_full.iloc[-1]
            exit_price = final_bar['close']
            trade = self._close_trade(
                direction=position, entry_price=entry_price, exit_price=exit_price,
                sl=sl, tp=tp, position_size=position_size,
                entry_time=entry_time, exit_time=final_bar.name,
                balance=balance, result='CLOSE_END',
                score=entry_score, regime=entry_regime, details=entry_details,
                entry_bar=entry_bar_idx, exit_bar=len(df_full) - 1,
            )
            balance += trade.pnl - trade.commission
            trades.append(trade)

        return trades, equity_curve

    def _close_trade(
        self, direction: str, entry_price: float, exit_price: float,
        sl: float, tp: float, position_size: float,
        entry_time, exit_time, balance: float, result: str,
        score: float, regime: str, details: Optional[Dict[str, Any]] = None,
        entry_bar: int = 0, exit_bar: int = 0,
    ) -> Trade:
        """Calcule le PnL et crée un objet Trade."""
        if direction == 'LONG':
            raw_pnl = position_size * (exit_price - entry_price)
        else:
            raw_pnl = position_size * (entry_price - exit_price)

        # Coûts de transaction (entrée + sortie)
        notional = position_size * entry_price
        commission = notional * self.commission_pct * 2

        pnl_net = raw_pnl - commission
        pnl_pct = (pnl_net / balance) * 100 if balance > 0 else 0.0

        return Trade(
            entry_time=entry_time,
            exit_time=exit_time,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            sl_price=sl,
            tp_price=tp,
            position_size=position_size,
            pnl=raw_pnl,
            pnl_pct=pnl_pct,
            result=result,
            score=score,
            market_regime=regime,
            commission=commission,
            entry_details=details or {},
        )

    # ─── Calcul des métriques ─────────────────────────────────────────────────

    def _compute_results(self, trades: List[Trade], equity_curve: List[float]) -> BacktestResults:
        """Calcule toutes les métriques de performance à partir du journal des trades."""
        equity = pd.Series(equity_curve)
        final_balance = equity.iloc[-1] if len(equity) > 0 else self.initial_balance

        # Rendements
        returns = equity.pct_change().dropna()
        total_return_pct = ((final_balance / self.initial_balance) - 1) * 100

        # Drawdown
        rolling_max = equity.cummax()
        drawdown = (equity - rolling_max) / rolling_max * 100
        max_dd = abs(drawdown.min())

        # Durée du drawdown maximum
        dd_duration = self._max_drawdown_duration(equity)

        # Ratios annualisés (hypothèse : données horaires par défaut)
        bars_per_year = self._estimate_bars_per_year()
        mean_r = returns.mean()
        std_r = returns.std()
        downside_r = returns[returns < 0].std()

        sharpe = (mean_r / std_r * math.sqrt(bars_per_year)) if std_r > 0 else 0.0
        sortino = (mean_r / downside_r * math.sqrt(bars_per_year)) if downside_r > 0 else 0.0
        calmar = (total_return_pct / max_dd) if max_dd > 0 else 0.0

        # Métriques des trades
        winners = [t for t in trades if t.pnl > 0]
        losers = [t for t in trades if t.pnl <= 0]
        win_rate = len(winners) / len(trades) if trades else 0.0
        avg_win = np.mean([t.pnl_pct for t in winners]) if winners else 0.0
        avg_loss = np.mean([t.pnl_pct for t in losers]) if losers else 0.0

        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        pnl_pcts = [t.pnl_pct for t in trades] if trades else [0.0]
        best_trade = max(pnl_pcts)
        worst_trade = min(pnl_pcts)

        # Durée moyenne des trades (en nombre de bougies)
        durations = []
        for t in trades:
            if t.entry_time and t.exit_time:
                try:
                    dur = (t.exit_time - t.entry_time).total_seconds()
                    tf_seconds = self._timeframe_seconds()
                    if tf_seconds > 0:
                        durations.append(dur / tf_seconds)
                except Exception as _exc:
                    log.debug(f"Erreur ignorée (non bloquante) : {_exc}")
        avg_duration = np.mean(durations) if durations else 0.0

        # Ratio R:R réalisé moyen
        realized_rr = []
        for t in trades:
            risk = abs(t.entry_price - t.sl_price)
            reward = abs(t.exit_price - t.entry_price)
            if risk > 0:
                realized_rr.append(reward / risk)
        avg_rr = np.mean(realized_rr) if realized_rr else 0.0

        start_date = self.df.index[0].strftime('%Y-%m-%d') if len(self.df) > 0 else 'N/A'
        end_date = self.df.index[-1].strftime('%Y-%m-%d') if len(self.df) > 0 else 'N/A'

        return BacktestResults(
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_date=start_date,
            end_date=end_date,
            broker_type=self.broker_type,
            initial_balance=self.initial_balance,
            final_balance=round(final_balance, 2),
            total_return_pct=round(total_return_pct, 3),
            max_drawdown_pct=round(max_dd, 3),
            max_drawdown_duration_bars=dd_duration,
            sharpe_ratio=round(sharpe, 4),
            sortino_ratio=round(sortino, 4),
            calmar_ratio=round(calmar, 4),
            profit_factor=round(profit_factor, 3),
            total_trades=len(trades),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=round(win_rate, 4),
            avg_win_pct=round(avg_win, 3),
            avg_loss_pct=round(avg_loss, 3),
            avg_rr_realized=round(avg_rr, 3),
            best_trade_pct=round(best_trade, 3),
            worst_trade_pct=round(worst_trade, 3),
            avg_trade_duration_bars=round(avg_duration, 1),
            equity_curve=equity_curve,
            trades=trades,
            params_used={
                'SCORE_MIN': self.config.get('SCORE_MIN'),
                'RISK_PCT': self.config.get('RISK_PCT'),
                'SL_ATR_MULT': self.sl_atr_mult,
                'TP_ATR_MULT': self.tp_atr_mult,
                'commission_pct': self.commission_pct * 100,
                'initial_balance': self.initial_balance,
            },
        )

    @staticmethod
    def _max_drawdown_duration(equity: pd.Series) -> int:
        """Calcule la durée maximale (en nombre de bougies) d'une période de drawdown."""
        peak = equity.iloc[0]
        max_duration = 0
        current_duration = 0
        for val in equity:
            if val >= peak:
                peak = val
                current_duration = 0
            else:
                current_duration += 1
                max_duration = max(max_duration, current_duration)
        return max_duration

    def _estimate_bars_per_year(self) -> float:
        """Estime le nombre de bougies par an selon le timeframe."""
        mapping = {
            '1m': 525_600, '5m': 105_120, '15m': 35_040,
            '30m': 17_520, '1h': 8_760, '4h': 2_190,
            '1d': 252, '1w': 52,
        }
        return mapping.get(self.timeframe, 8_760)

    def _timeframe_seconds(self) -> int:
        """Retourne la durée en secondes d'un timeframe."""
        mapping = {
            '1m': 60, '5m': 300, '15m': 900, '30m': 1800,
            '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800,
        }
        return mapping.get(self.timeframe, 3600)
