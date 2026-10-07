import pandas as pd
from superbot.ml.walk_forward import WalkForwardOptimizer
from superbot.ml.probabilistic_scorer import ProbabilisticScorer

def test_walk_forward_optimizer_basic():
    """Vérifie le fonctionnement de base de l'optimiseur Walk-Forward."""
    optimizer = WalkForwardOptimizer()
    
    # Créer un faux historique de trades
    trades = [
        {'symbol': 'BTC/USDT', 'signal_score': 6.0, 'pnl': 100.0, 'status': 'closed'},
        {'symbol': 'BTC/USDT', 'signal_score': 5.0, 'pnl': -50.0, 'status': 'closed'},
        {'symbol': 'BTC/USDT', 'signal_score': 7.0, 'pnl': 200.0, 'status': 'closed'},
        {'symbol': 'BTC/USDT', 'signal_score': 4.0, 'pnl': -100.0, 'status': 'closed'},
    ] * 10  # 40 trades au total (min 20 requis par l'optimiseur)
    
    df = pd.DataFrame(trades)
    
    # Exécuter l'optimisation
    best_params = optimizer.optimize(df)
    
    # Seuil 6 : 20 trades gagnants (PF infini) ; seuil 5 : PF 6 ; seuil 7 : < 20 trades
    assert best_params == {'SCORE_MIN': 6}


def test_walk_forward_ignores_unverified_trades():
    optimizer = WalkForwardOptimizer()
    trades = [{'signal_score': 9.0, 'pnl': 10.0, 'verified': False}] * 30
    assert optimizer.optimize(pd.DataFrame(trades)) == {'SCORE_MIN': 6}  # inchangé : rien de vérifié


def test_effective_score_min_never_below_config(monkeypatch):
    from superbot.brain.strategy_engine import StrategyEngine
    monkeypatch.setattr("superbot.config.SCORE_MIN", 8)
    assert StrategyEngine.effective_score_min(5) == 8      # walk-forward / adaptation ne baissent pas
    assert StrategyEngine.effective_score_min(9) == 9      # mais peuvent durcir
    assert StrategyEngine.effective_score_min(12) == 10    # plafond
    assert StrategyEngine.effective_score_min(None) == 8

def test_probabilistic_scorer_predict_proba():
    """Vérifie le fonctionnement du Scorer probabiliste en mode entraîné et non-entraîné."""
    # Utiliser un chemin temporaire pour ne pas écraser le modèle de production
    scorer = ProbabilisticScorer(model_path="resources/test_logistic_scorer.pkl")
    
    # Par défaut (non entraîné), il doit retourner 0.5
    row = pd.Series({'rsi': 60, 'macd_hist': 1.5, 'adx': 30, 'close': 100, 'bb_upper': 102, 'bb_lower': 98, 'atr': 2})
    assert scorer.predict_proba(row) == 0.5
