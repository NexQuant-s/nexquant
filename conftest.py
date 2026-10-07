"""Configuration de test partagée.

L'ancien `pytest.ini` s'appuyait sur le plugin `pytest-env` (`env = BROKER_TYPE=paper`),
qui n'est pas installé : l'option était ignorée (warning « Unknown config option: env »)
et le code n'était de toute façon jamais exécuté. De plus, « paper » n'est pas un type
de broker valide ici (`binance`, `alpaca`, `mt5`) — le mode « sûr » est `BACKTEST_MODE`,
qui court-circuite la validation des identifiants broker dans `superbot.config`.

On l'active ici avant tout import de `superbot.config`, pour que la suite ne dépende
jamais des clés API / identifiants MT5 du `.env` et ne puisse pas toucher un broker live.

Isolation des fichiers d'état : le bot peut tourner en direct depuis ce dossier. Les
logs, le journal des trades, l'état persistant, la base SQLite, les rapports et le modèle
ML sont redirigés vers un dossier temporaire (variables lues par `superbot.config` ;
`load_dotenv` ne surcharge pas les variables déjà définies).
"""

import os
import shutil
import tempfile
from pathlib import Path

os.environ["BACKTEST_MODE"] = "true"
# Univers d'instruments fixe : les tests ne doivent pas dépendre du `.env` local
# (les brokers simulés des tests ne fournissent pas de liste par défaut).
for _key in ("INSTRUMENTS", "INSTRUMENTS_MT5"):
    os.environ[_key] = "EURUSD,USDJPY,XAUUSD"
for _key in ("NEWS_ASSETS", "NEWS_ASSETS_MT5"):
    os.environ[_key] = "EUR,USD,JPY,GOLD"

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="nexquant_tests_"))
_LIVE_MODEL = Path(__file__).parent / "resources" / "ensemble_scorer.pkl"
_TEST_MODEL = _TEST_ROOT / "ensemble_scorer.pkl"
if _LIVE_MODEL.exists():
    # Copie : les tests gardent le même modèle de départ sans jamais réécrire l'original.
    shutil.copy2(_LIVE_MODEL, _TEST_MODEL)

os.environ["NEXQUANT_TEST_ROOT"] = str(_TEST_ROOT)
os.environ["NEXQUANT_LOG_DIR"] = str(_TEST_ROOT / "logs")
os.environ["NEXQUANT_REPORTS_DIR"] = str(_TEST_ROOT / "reports")
os.environ["NEXQUANT_MODEL_PATH"] = str(_TEST_MODEL)
os.environ["DB_PATH"] = str(_TEST_ROOT / "db" / "nexquant_test.db")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
