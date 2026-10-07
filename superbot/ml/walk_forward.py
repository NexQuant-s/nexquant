import logging
import time
import pandas as pd
from typing import Dict, Any

log = logging.getLogger("ml.walk_forward")


class WalkForwardOptimizer:
    """
    Recalibration périodique du seuil SCORE_MIN à partir des trades réels.

    Pour chaque seuil candidat, on calcule le profit factor RÉALISÉ des trades vérifiés
    broker dont le score de signal atteint ce seuil (un trade sous le seuil n'aurait pas
    été pris). Un seuil n'est retenu que s'il garde au moins `min_trades` trades.

    L'ancienne version ajoutait une pénalité arbitraire (SCORE_MIN × 1.5) aux pertes et
    « optimisait » aussi RSI_OB / ADX_TREND sans les simuler : elle convergeait vers 5.
    Le seuil retenu ne peut de toute façon pas descendre sous SCORE_MIN du .env
    (StrategyEngine.effective_score_min).
    """

    def __init__(self, candidates=(5, 6, 7, 8, 9), min_trades: int = 20):
        self.param_grid = {'SCORE_MIN': list(candidates)}
        self.min_trades = int(min_trades)
        self.best_params = {'SCORE_MIN': 6}
        self.last_calibration_time = time.time()
        self.is_optimizing = False

    @staticmethod
    def _is_verified(row) -> bool:
        verified = row.get('verified')
        if verified is not None and not pd.isna(verified):
            return bool(verified)
        # Anciennes lignes broker : ticket présent mais pas de champ 'verified'
        position_id = row.get('position_id')
        return position_id is not None and not pd.isna(position_id)

    def _usable_trades(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """Trades avec P&L et score de signal ; uniquement les vérifiés broker si l'information existe."""
        if trades_df is None or trades_df.empty or 'pnl' not in trades_df or 'signal_score' not in trades_df:
            return pd.DataFrame()
        df = trades_df.copy()
        if 'verified' in df.columns or 'position_id' in df.columns:
            df = df[df.apply(self._is_verified, axis=1)]
        df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce')
        df['signal_score'] = pd.to_numeric(df['signal_score'], errors='coerce')
        return df.dropna(subset=['pnl', 'signal_score'])

    @staticmethod
    def profit_factor(pnl: pd.Series) -> float:
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = -pnl[pnl < 0].sum()
        if gross_loss <= 0:
            return float('inf') if gross_profit > 0 else 0.0
        return float(gross_profit / gross_loss)

    def optimize(self, trades_df: pd.DataFrame) -> Dict[str, Any]:
        """Retourne {'SCORE_MIN': seuil} au meilleur profit factor réalisé (sinon le seuil courant)."""
        df = self._usable_trades(trades_df)
        if len(df) < self.min_trades:
            log.warning(f"Walk-Forward : {len(df)} trades vérifiés avec score (< {self.min_trades}) — seuil inchangé.")
            return dict(self.best_params)

        self.is_optimizing = True
        best_pf, best_score = -1.0, self.best_params['SCORE_MIN']
        for threshold in self.param_grid['SCORE_MIN']:
            kept = df[df['signal_score'] >= threshold]
            if len(kept) < self.min_trades:
                continue
            pf = self.profit_factor(kept['pnl'])
            log.info(f"Walk-Forward : SCORE_MIN={threshold} → {len(kept)} trades, PF={pf:.2f}")
            if pf > best_pf:
                best_pf, best_score = pf, threshold

        self.best_params = {'SCORE_MIN': best_score}
        self.last_calibration_time = time.time()
        self.is_optimizing = False
        log.info(f"✅ Walk-Forward terminé : SCORE_MIN={best_score} (PF réalisé {best_pf:.2f})")
        return dict(self.best_params)
