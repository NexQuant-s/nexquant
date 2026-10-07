"""
Réentraînement du modèle ML (EnsembleScorer) sur les seuls trades vérifiés broker,
avec validation hors échantillon avant toute réactivation.

Usage (depuis la racine du dépôt) :
    python -m artifacts.retrain_ml_scorer                  # évaluation seule (aucune écriture)
    python -m artifacts.retrain_ml_scorer --apply          # remplace le modèle si validé
    python -m artifacts.retrain_ml_scorer --journal chemin/vers/trades_mt5.jsonl

Critères (superbot.config) : au moins ML_MIN_VERIFIED_TRADES trades vérifiés avec features,
et AUC hors échantillon ≥ ML_MIN_AUC sur les 30 % de trades les plus récents (split temporel).
Si validé, passer ML_SHADOW_MODE=false dans .env pour que le modèle filtre à nouveau.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd
from sklearn.metrics import roc_auc_score

from superbot import config
from superbot.ml.probabilistic_scorer import EnsembleScorer
from superbot.risk.modules.trade_recorder import dedupe_trade_rows, _parse_ts

FEATURE_KEYS = ("rsi", "adx", "bb_pos", "atr_pct")


def is_verified(row: dict) -> bool:
    """P&L lu chez le broker. Les anciennes lignes broker ont un ticket mais pas de champ `verified`."""
    return bool(row.get("verified", bool(row.get("position_id"))))


def load_verified_trades(journal: Path) -> pd.DataFrame:
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = dedupe_trade_rows(rows, [])
    usable = [
        r for r in rows
        if is_verified(r) and r.get("pnl") is not None and all(r.get(k) is not None for k in FEATURE_KEYS)
    ]
    usable.sort(key=lambda r: _parse_ts(r.get("timestamp")))
    df = pd.DataFrame(usable)
    if not df.empty:
        df["target"] = (df["pnl"].astype(float) > 0).astype(int)
    return df


def evaluate(df: pd.DataFrame, train_frac: float = 0.7):
    """Entraîne sur le passé, mesure l'AUC sur le futur. Retourne (auc, n_test)."""
    split = int(len(df) * train_frac)
    train, test = df.iloc[:split], df.iloc[split:]
    if len(train) < 20 or test["target"].nunique() < 2:
        return None, len(test)
    with tempfile.TemporaryDirectory() as tmp:
        scorer = EnsembleScorer(model_path=os.path.join(tmp, "eval.pkl"))
        if not scorer.train(train):
            return None, len(test)
        preds = [scorer.predict_proba(row) for _, row in test.iterrows()]
    return float(roc_auc_score(test["target"], preds)), len(test)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--journal", default=str(config.TRADE_LOG_FILE))
    parser.add_argument("--apply", action="store_true", help="Remplacer le modèle si la validation réussit")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # console Windows cp1252

    df = load_verified_trades(Path(args.journal))
    n = len(df)
    print(f"Trades vérifiés broker avec features : {n} (minimum requis : {config.ML_MIN_VERIFIED_TRADES})")
    if n < config.ML_MIN_VERIFIED_TRADES:
        print("➡️  Pas assez de données propres : garder ML_SHADOW_MODE=true.")
        return 1

    auc, n_test = evaluate(df)
    if auc is None:
        print("➡️  Évaluation impossible (échantillon de test sans diversité) : garder ML_SHADOW_MODE=true.")
        return 1
    print(f"AUC hors échantillon : {auc:.3f} sur {n_test} trades (seuil : {config.ML_MIN_AUC})")
    if auc < config.ML_MIN_AUC:
        print("➡️  Modèle non prédictif : garder ML_SHADOW_MODE=true.")
        return 1

    if not args.apply:
        print("✅ Validation réussie. Relancer avec --apply pour remplacer le modèle.")
        return 0

    model_path = Path(config.ML_MODEL_PATH)
    if model_path.exists():
        backup = model_path.with_suffix(".pkl.bak")
        shutil.copy2(model_path, backup)
        print(f"Ancien modèle sauvegardé : {backup}")
    scorer = EnsembleScorer(model_path=str(model_path))
    scorer.lr_trained = scorer.rf_trained = scorer.gb_trained = False
    scorer.train(df)
    print(f"✅ Modèle réentraîné sur {n} trades → {model_path}. Passer ML_SHADOW_MODE=false dans .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
