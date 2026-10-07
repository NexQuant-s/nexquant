"""Garde-fou : la suite de tests ne doit jamais écrire dans les fichiers du bot live."""

import os
from pathlib import Path

from superbot import config


def _is_under_test_root(path) -> bool:
    root = Path(os.environ["NEXQUANT_TEST_ROOT"]).resolve()
    return root in Path(path).resolve().parents


def test_state_paths_are_redirected_to_temp_dir():
    for path in (
        config.LOG_DIR / "x",
        config.TRADE_LOG_FILE,
        config.BUG_LOG_FILE,
        config.LOG_FILE,
        config.DB_PATH,
        config.ML_MODEL_PATH,
        Path(config.REPORTS_DIR) / "x",
    ):
        assert _is_under_test_root(path), f"{path} pointe hors du dossier temporaire des tests"


def test_report_generator_uses_redirected_dir():
    from superbot.brain.report_generator import ReportGenerator

    assert _is_under_test_root(Path(ReportGenerator().REPORTS_DIR) / "x")


def test_default_database_uses_redirected_path():
    # get_db() sans argument (utilisé par SessionManager) ouvrait superbot/db/nexquant.db en dur
    from superbot.db.database import NexQuantDB

    assert _is_under_test_root(NexQuantDB().db_path)


def test_scorer_uses_redirected_model_path():
    from superbot.ml.probabilistic_scorer import EnsembleScorer

    assert _is_under_test_root(EnsembleScorer().model_path)
