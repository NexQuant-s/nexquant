"""
🧠 NexQuant V3 — Online Learner
Déclenche le partial_fit() de l'EnsembleScorer après chaque trade fermé.
Sauvegarde/restauration automatique du modèle.
Intégration avec le PerformanceLearner pour l'orchestration complète.
"""
import logging
import threading
from typing import Optional, Dict, Any
import pandas as pd

log = logging.getLogger("ml.online_learner")


class OnlineLearner:
    """
    Gestion du cycle de vie de l'apprentissage en ligne.
    - Reçoit les trades fermés et met à jour EnsembleScorer
    - Sauvegarde périodique du modèle (toutes les 50 trades)
    - Rapport de performance des modèles
    """

    def __init__(self, scorer=None, db=None):
        """
        Args:
            scorer: Instance d'EnsembleScorer (optionnel, crée un nouveau si None)
            db: Instance de NexQuantDB (optionnel)
        """
        self.db = db
        self._lock = threading.Lock()
        self._trades_since_save = 0
        self._total_trades_learned = 0
        self._win_count = 0
        self._loss_count = 0

        # Importer le scorer
        if scorer is not None:
            self.scorer = scorer
        else:
            try:
                from superbot.ml.probabilistic_scorer import EnsembleScorer
                self.scorer = EnsembleScorer()
                log.info("OnlineLearner: EnsembleScorer créé")
            except Exception as e:
                log.warning(f"OnlineLearner: impossible de créer EnsembleScorer: {e}")
                self.scorer = None

    def on_trade_closed(self, trade: Dict[str, Any], df_row: Optional[pd.Series] = None,
                        context: dict = None) -> None:
        """
        Appeler quand un trade se ferme.
        Met à jour le scorer avec le résultat du trade.

        Args:
            trade: Dict avec au moins 'pnl', 'strategy_name', 'symbol'
            df_row: Ligne de DataFrame avec les indicateurs au moment de l'entrée
            context: Contexte additionnel (régime, session, sentiment...)
        """
        if self.scorer is None:
            return
        if not trade.get('verified', True):
            # P&L estimé (clôture non retrouvée chez le broker) : ne pas apprendre sur une étiquette douteuse.
            log.info(f"OnlineLearner: trade {trade.get('symbol')} non vérifié broker — ignoré pour l'apprentissage")
            return

        pnl = float(trade.get('pnl', 0) or 0)
        target = 1 if pnl > 0 else 0

        with self._lock:
            try:
                if df_row is not None and isinstance(df_row, pd.Series):
                    ctx = context or {}
                    # Enrichir le contexte avec les infos du trade
                    ctx.setdefault('strategy_wr_30d', 0.5)
                    ctx.setdefault('consecutive_wins', 0)
                    self.scorer.partial_fit(df_row, target, ctx)
                    self._trades_since_save += 1
                    self._total_trades_learned += 1
                    if target == 1:
                        self._win_count += 1
                    else:
                        self._loss_count += 1

                    log.debug(
                        f"OnlineLearner: trade appris | sym={trade.get('symbol')} "
                        f"pnl={pnl:.2f} target={target} | total={self._total_trades_learned}"
                    )

                    # Sauvegarde périodique
                    if self._trades_since_save >= 50:
                        self.scorer.save()
                        self._trades_since_save = 0
                        log.info(f"OnlineLearner: modèle sauvegardé | {self._total_trades_learned} trades appris")

            except Exception as e:
                log.error(f"OnlineLearner.on_trade_closed error: {e}")

    def get_prediction(self, df_row: pd.Series, context: dict = None) -> float:
        """
        Retourne la probabilité de gain pour le setup actuel.

        Returns:
            float: 0.0 (perdant) à 1.0 (gagnant), 0.5 si non entraîné
        """
        if self.scorer is None:
            return 0.5
        try:
            return self.scorer.predict_proba(df_row, context)
        except Exception as e:
            log.debug(f"Prédiction error: {e}")
            return 0.5

    def get_model_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du modèle."""
        total = self._win_count + self._loss_count
        wr = self._win_count / total if total > 0 else 0.0
        return {
            'total_trades_learned': self._total_trades_learned,
            'win_count': self._win_count,
            'loss_count': self._loss_count,
            'win_rate': wr,
            'lr_trained': getattr(self.scorer, 'lr_trained', False) if self.scorer else False,
            'rf_trained': getattr(self.scorer, 'rf_trained', False) if self.scorer else False,
            'gb_trained': getattr(self.scorer, 'gb_trained', False) if self.scorer else False,
            'ensemble_weights': getattr(self.scorer, 'weights', [0.33, 0.33, 0.33]) if self.scorer else [],
        }

    def batch_train(self, trade_history_df: pd.DataFrame) -> bool:
        """
        Entraînement batch initial ou hebdomadaire complet.

        Args:
            trade_history_df: DataFrame avec colonnes features + 'target' (0/1)

        Returns:
            True si entraînement réussi
        """
        if self.scorer is None:
            return False
        try:
            result = self.scorer.train(trade_history_df)
            if result:
                log.info(f"OnlineLearner: batch train réussi | {len(trade_history_df)} trades")
            return result
        except Exception as e:
            log.error(f"OnlineLearner.batch_train error: {e}")
            return False

    def flush(self) -> bool:
        """
        Force la sauvegarde immédiate du modèle, quelle que soit la progression.

        BUG-14 FIX: Le modèle était sauvegardé seulement toutes les 50 trades.
        Si le bot s'arrête après 49 trades, tous les apprentissages sont perdus.
        Appeler cette méthode dans SuperBot.stop() pour garantir la persistance.

        Returns:
            True si la sauvegarde a réussi
        """
        if self.scorer is None:
            return False
        if self._trades_since_save == 0:
            log.debug("OnlineLearner.flush: aucun apprentissage non sauvegardé, rien à faire")
            return True
        with self._lock:
            try:
                self.scorer.save()
                log.info(
                    f"OnlineLearner.flush: modèle sauvegardé à l'arrêt "
                    f"({self._trades_since_save} trades non sauvegardés persistance forcée) | "
                    f"Total: {self._total_trades_learned} trades appris"
                )
                self._trades_since_save = 0
                return True
            except Exception as e:
                log.error(f"OnlineLearner.flush error: {e}")
                return False
