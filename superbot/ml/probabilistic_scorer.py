"""
🧠 NexQuant V3 — EnsembleScorer ML
Remplace le simple LogisticRegression (5 features) par un ensemble de 3 modèles (20 features).
- LogisticRegression (interprétable, rapide)
- RandomForestClassifier (robuste, non-linéaire)
- GradientBoostingClassifier (puissant, régularisé)
Vote pondéré : poids adaptatifs basés sur win_rate des 30 derniers trades.
Online learning : partial_fit() via SGDClassifier wrapper.
"""
import os
import numpy as np
import pandas as pd
from typing import Dict, List
import logging
import joblib
from sklearn.linear_model import SGDClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler

log = logging.getLogger("ml.ensemble_scorer")

# ---------------------------------------------------------------------------
# Features étendues (20 features selon le plan V3)
# ---------------------------------------------------------------------------
FEATURES_BASIC = ['rsi', 'macd_hist', 'adx', 'bb_pos', 'atr_pct']

FEATURES_EXTENDED = [
    # Techniques (9)
    'rsi', 'macd_hist', 'adx', 'bb_pos', 'atr_pct',
    'ema_cross_signal', 'supertrend_signal', 'ichimoku_signal', 'volume_zscore',
    # Contextuels (5)
    'regime_id', 'session_id', 'hour_of_day', 'day_of_week', 'spread_pips',
    # Sentiment (4)
    'fear_greed_norm', 'news_sentiment', 'social_sentiment', 'on_chain_signal',
    # Performance (2)
    'strategy_wr_30d', 'consecutive_wins',
]

# Régimes et sessions encodés
REGIME_MAP = {
    'trending_bull': 2, 'trending': 2, 'BULLISH': 2,
    'trending_bear': -2, 'BEARISH': -2,
    'ranging': 0, 'RANGE': 0,
    'breakout': 3, 'BREAKOUT': 3,
    'pre_breakout': 1,
    'high_volatility': -1, 'HIGH_VOL': -1,
}
SESSION_MAP = {
    'ASIA': 1, 'PRE_LONDON': 2, 'LONDON': 3,
    'OVERLAP': 4, 'NEW_YORK': 5, 'OFF_HOURS': 0,
}


def _extract_extended_features(df_row: pd.Series, context: dict = None) -> np.ndarray:
    """
    Extrait les 20 features depuis une ligne de DataFrame enrichie + contexte.
    Les valeurs manquantes sont remplacées par des neutres.
    """
    ctx = context or {}
    close = df_row.get('close', 1) or 1

    def _recorded(key):
        """Valeur déjà calculée à l'entrée (lignes du journal des trades), sinon None."""
        value = df_row.get(key)
        return float(value) if value is not None and pd.notna(value) else None

    # Techniques de base
    rsi = float(df_row.get('rsi', 50) or 50)
    macd_hist = float(df_row.get('macd_histogram', df_row.get('macd_hist', 0)) or 0)
    adx = float(df_row.get('adx', 20) or 20)
    bb_pos = _recorded('bb_pos')
    if bb_pos is None:
        bb_upper = float(df_row.get('bb_upper', close * 1.01) or close * 1.01)
        bb_lower = float(df_row.get('bb_lower', close * 0.99) or close * 0.99)
        bb_pos = (close - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
    atr_pct = _recorded('atr_pct')
    if atr_pct is None:
        atr = float(df_row.get('atr', 0) or 0)
        atr_pct = (atr / close) * 100 if close > 0 else 0

    # Signaux techniques
    ema_fast = float(df_row.get('ema_fast', close) or close)
    ema_slow = float(df_row.get('ema_slow', close) or close)
    ema_cross_signal = 1.0 if ema_fast > ema_slow else (-1.0 if ema_fast < ema_slow else 0.0)
    supertrend_dir = float(df_row.get('supertrend_direction', 0) or 0)
    supertrend_signal = 1.0 if supertrend_dir > 0 else (-1.0 if supertrend_dir < 0 else 0.0)
    # Ichimoku simplifié (signal via vwap comme proxy)
    vwap = float(df_row.get('vwap', close) or close)
    ichimoku_signal = 1.0 if close > vwap else (-1.0 if close < vwap else 0.0)
    # Volume Z-score
    volume_zscore = float(ctx.get('volume_zscore', 0) or 0)

    # Contexte (régime et heure de l'ENTRÉE si enregistrés, sinon instant présent)
    regime_str = str(ctx.get('regime') or df_row.get('market_regime') or 'ranging')
    regime_id = float(REGIME_MAP.get(regime_str, 0))
    session_str = str(ctx.get('session', 'LONDON'))
    session_id = float(SESSION_MAP.get(session_str, 3))
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    hour_of_day = _recorded('hour_of_day')
    hour_of_day = float(now.hour) if hour_of_day is None else hour_of_day
    day_of_week = _recorded('day_of_week')
    day_of_week = float(now.weekday()) if day_of_week is None else day_of_week
    spread_pips = float(ctx.get('spread_pips', 0.5) or 0.5)

    # Sentiment
    fear_greed_raw = float(ctx.get('fear_greed_index', 50) or 50)
    fear_greed_norm = fear_greed_raw / 100.0
    news_sentiment = float(ctx.get('news_sentiment', 0) or 0)
    social_sentiment = float(ctx.get('social_sentiment', 0) or 0)
    on_chain_signal = float(ctx.get('on_chain_signal', 0) or 0)

    # Performance historique
    strategy_wr_30d = float(ctx.get('strategy_wr_30d', 0.5) or 0.5)
    consecutive_wins = float(ctx.get('consecutive_wins', 0) or 0)

    return np.array([[
        rsi, macd_hist, adx, bb_pos, atr_pct,
        ema_cross_signal, supertrend_signal, ichimoku_signal, volume_zscore,
        regime_id, session_id, hour_of_day, day_of_week, spread_pips,
        fear_greed_norm, news_sentiment, social_sentiment, on_chain_signal,
        strategy_wr_30d, consecutive_wins,
    ]])


class EnsembleScorer:
    """
    3 modèles en ensemble (vote pondéré par performance récente) :
    1. LogisticRegression (rapide, interprétable) — baseline
    2. RandomForestClassifier (robuste, non-linéaire) — 20 features
    3. SGDClassifier (online learning) — incrémental avec partial_fit()

    Vote pondéré : poids adaptatifs basés sur win_rate des 30 derniers trades.
    """

    def __init__(self, model_path: str = None):
        if model_path is None:
            from superbot.config import ML_MODEL_PATH
            model_path = ML_MODEL_PATH
        self.model_path = model_path
        self.scaler = StandardScaler()
        self.scaler_fitted = False

        # Modèle 1 : Logistic Regression (compatible partial_fit via SGD)
        self.lr = SGDClassifier(
            loss='log_loss', penalty='l2', alpha=0.01,
            max_iter=1000, random_state=42, class_weight='balanced'
        )
        self.lr_trained = False

        # Modèle 2 : Random Forest (batch re-train hebdomadaire)
        self.rf = RandomForestClassifier(
            n_estimators=100, max_depth=8, random_state=42,
            class_weight='balanced', n_jobs=-1
        )
        self.rf_trained = False

        # Modèle 3 : Gradient Boosting (batch, plus puissant)
        self.gb = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.05,
            subsample=0.8, random_state=42
        )
        self.gb_trained = False

        # Poids d'ensemble (adaptatifs)
        self.weights = [0.33, 0.34, 0.33]  # [LR, RF, GB]
        self.recent_trades: List[Dict] = []  # Buffer pour online learning

        self.load()

    def _extract_features(self, df_row: pd.Series, context: dict = None) -> np.ndarray:
        """Extrait les 20 features étendues."""
        return _extract_extended_features(df_row, context)

    @property
    def is_trained(self) -> bool:
        """Compatibilité V2 : retourne vrai si au moins un des modèles est entraîné."""
        return self.lr_trained or self.rf_trained or self.gb_trained

    def predict_proba(self, df_row: pd.Series, context: dict = None) -> float:
        """
        Retourne la probabilité de gain (0.0 à 1.0) via vote pondéré.
        Fallback sur 0.5 si aucun modèle n'est entraîné.
        """
        X = self._extract_features(df_row, context)

        if self.scaler_fitted:
            try:
                X_scaled = self.scaler.transform(X)
            except Exception:
                X_scaled = X
        else:
            X_scaled = X

        proba_list = []
        weight_list = []

        if self.lr_trained:
            try:
                p = float(self.lr.predict_proba(X_scaled)[0][1])
                proba_list.append(p)
                weight_list.append(self.weights[0])
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        if self.rf_trained:
            try:
                p = float(self.rf.predict_proba(X_scaled)[0][1])
                proba_list.append(p)
                weight_list.append(self.weights[1])
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        if self.gb_trained:
            try:
                p = float(self.gb.predict_proba(X_scaled)[0][1])
                proba_list.append(p)
                weight_list.append(self.weights[2])
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")

        if not proba_list:
            return 0.5

        total_w = sum(weight_list)
        if total_w <= 0:
            return sum(proba_list) / len(proba_list)

        weighted = sum(p * w for p, w in zip(proba_list, weight_list, strict=True)) / total_w
        return float(weighted)

    def partial_fit(self, df_row: pd.Series, target: int, context: dict = None):
        """
        Online learning : met à jour le LR incrémentalement après chaque trade fermé.
        target = 1 (gagnant), 0 (perdant)
        """
        X = self._extract_features(df_row, context)

        if not self.scaler_fitted:
            self.scaler.partial_fit(X)
            self.scaler_fitted = True

        try:
            X_scaled = self.scaler.transform(X)
            self.lr.partial_fit(X_scaled, [target], classes=[0, 1])
            self.lr_trained = True
        except Exception as e:
            log.debug(f"partial_fit LR error: {e}")

        # Buffer pour re-train batch RF/GB
        self.recent_trades.append({'X': X, 'y': target})
        if len(self.recent_trades) > 500:
            self.recent_trades = self.recent_trades[-500:]

        # Re-train RF/GB tous les 50 nouveaux trades
        if len(self.recent_trades) % 50 == 0:
            self._batch_retrain()

    def _batch_retrain(self):
        """Re-train RF et GB sur les 500 derniers trades."""
        if len(self.recent_trades) < 20:
            return
        try:
            X_all = np.vstack([t['X'] for t in self.recent_trades])
            y_all = np.array([t['y'] for t in self.recent_trades])

            if len(np.unique(y_all)) < 2:
                return  # Pas assez de diversité

            if not self.scaler_fitted:
                self.scaler.fit(X_all)
                self.scaler_fitted = True

            X_scaled = self.scaler.transform(X_all)

            self.rf.fit(X_scaled, y_all)
            self.rf_trained = True
            log.info(f"RandomForest re-train | {len(y_all)} trades | WR={y_all.mean():.1%}")

            if len(self.recent_trades) >= 50:
                self.gb.fit(X_scaled, y_all)
                self.gb_trained = True
                log.info("GradientBoosting re-train done")

            # Mise à jour des poids selon les win rates récents (derniers 30 trades)
            self._update_weights()
            self.save()
        except Exception as e:
            log.warning(f"Batch retrain error: {e}")

    def _update_weights(self):
        """Met à jour les poids d'ensemble selon les performances récentes."""
        recent = self.recent_trades[-30:]
        if len(recent) < 10:
            return

        X_recent = np.vstack([t['X'] for t in recent])
        y_recent = np.array([t['y'] for t in recent])
        X_scaled = self.scaler.transform(X_recent)

        accuracies = []
        for model, trained in [(self.lr, self.lr_trained), (self.rf, self.rf_trained), (self.gb, self.gb_trained)]:
            if trained:
                try:
                    preds = model.predict(X_scaled)
                    acc = (preds == y_recent).mean()
                    accuracies.append(max(acc, 0.01))
                except Exception:
                    accuracies.append(0.01)
            else:
                accuracies.append(0.01)

        total = sum(accuracies)
        if total > 0:
            self.weights = [a / total for a in accuracies]
            log.debug(f"Ensemble weights updated: LR={self.weights[0]:.2f} RF={self.weights[1]:.2f} GB={self.weights[2]:.2f}")

    def train(self, trade_history_df: pd.DataFrame):
        """Entraînement initial complet sur historique."""
        if len(trade_history_df) < 20:
            log.warning("Pas assez de données (min 20 trades)")
            return False

        X_list = []
        for _, row in trade_history_df.iterrows():
            X_list.append(self._extract_features(row, context={})[0])
            
        X = np.array(X_list)
        y = trade_history_df['target'].values

        if len(np.unique(y)) < 2:
            log.warning("Pas assez de diversité dans les trades")
            return False

        self.scaler.fit(X)
        self.scaler_fitted = True
        X_scaled = self.scaler.transform(X)

        self.lr.fit(X_scaled, y)
        self.lr_trained = True

        if len(trade_history_df) >= 50:
            self.rf.fit(X_scaled, y)
            self.rf_trained = True
            self.gb.fit(X_scaled, y)
            self.gb_trained = True

        acc = self.lr.score(X_scaled, y)
        log.info(f"EnsembleScorer entraîné | {len(y)} trades | LR acc={acc:.1%}")
        self.save()
        return True

    def save(self):
        """Sauvegarde le scorer."""
        try:
            os.makedirs(os.path.dirname(self.model_path) if os.path.dirname(self.model_path) else '.', exist_ok=True)
            joblib.dump({
                'lr': self.lr, 'rf': self.rf, 'gb': self.gb,
                'scaler': self.scaler, 'weights': self.weights,
                'lr_trained': self.lr_trained, 'rf_trained': self.rf_trained,
                'gb_trained': self.gb_trained, 'scaler_fitted': self.scaler_fitted,
            }, self.model_path)
            log.debug(f"EnsembleScorer sauvegardé -> {self.model_path}")
        except Exception as e:
            log.error(f"Erreur sauvegarde EnsembleScorer: {e}")

    def load(self):
        """Charge le scorer depuis le disque."""
        if os.path.exists(self.model_path):
            try:
                data = joblib.load(self.model_path)
                if isinstance(data, dict):
                    self.lr = data.get('lr', self.lr)
                    self.rf = data.get('rf', self.rf)
                    self.gb = data.get('gb', self.gb)
                    self.scaler = data.get('scaler', self.scaler)
                    self.weights = data.get('weights', self.weights)
                    self.lr_trained = data.get('lr_trained', False)
                    self.rf_trained = data.get('rf_trained', False)
                    self.gb_trained = data.get('gb_trained', False)
                    self.scaler_fitted = data.get('scaler_fitted', False)
                    log.info(f"EnsembleScorer chargé depuis {self.model_path} | LR={self.lr_trained} RF={self.rf_trained} GB={self.gb_trained}")
            except Exception as e:
                log.error(f"Erreur chargement EnsembleScorer: {e}")


# ---------------------------------------------------------------------------
# Compatibilité backward avec ProbabilisticScorer (import transparent)
# ---------------------------------------------------------------------------
class ProbabilisticScorer(EnsembleScorer):
    """
    Alias de compatibilité : les anciens imports de ProbabilisticScorer
    utilisent automatiquement l'EnsembleScorer V3.
    """
    pass
