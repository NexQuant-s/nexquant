import os
import tempfile
from datetime import datetime, timezone
import pandas as pd
import numpy as np

from superbot.broker.symbol_specs import is_weekend_market
from superbot.brain.session_manager import SessionManager
from superbot.brain.strategy_engine import StrategyEngine
from superbot.brain.report_generator import ReportGenerator


class TestWeekendCryptoAndReports:

    def test_weekend_market_detection(self):
        # Saturday at 12:00 UTC -> Weekend
        sat = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
        assert is_weekend_market(sat) is True

        # Sunday at 18:00 UTC -> Weekend (before 21h)
        sun_early = datetime(2026, 7, 26, 18, 0, 0, tzinfo=timezone.utc)
        assert is_weekend_market(sun_early) is True

        # Sunday at 21:30 UTC -> Traditional markets preparing open
        sun_late = datetime(2026, 7, 26, 21, 30, 0, tzinfo=timezone.utc)
        assert is_weekend_market(sun_late) is False

        # Wednesday at 14:00 UTC -> Weekday
        wed = datetime(2026, 7, 22, 14, 0, 0, tzinfo=timezone.utc)
        assert is_weekend_market(wed) is False

        # Friday at 22:30 UTC -> Weekend starts
        fri_late = datetime(2026, 7, 24, 22, 30, 0, tzinfo=timezone.utc)
        assert is_weekend_market(fri_late) is True

    def test_session_manager_restrictions(self):
        sm = SessionManager(daily_target_eur=100.0)

        # 1. Simulate Weekend
        sm._current_session_name = "WEEKEND_CRYPTO"
        sm._current_session = {"allow_new_trades": True}

        # Crypto allowed
        allowed, msg = sm.can_trade_symbol("BTCUSD")
        assert allowed is True

        allowed, msg = sm.can_trade_symbol("ETHUSD")
        assert allowed is True

        # Forex & commodities forbidden on weekend
        allowed, msg = sm.can_trade_symbol("EURUSD")
        assert allowed is False
        assert "réservés aux cryptos" in msg

        allowed, msg = sm.can_trade_symbol("XAUUSD")
        assert allowed is False
        assert "réservés aux cryptos" in msg

        # 2. Simulate Weekday (LONDON session)
        sm._current_session_name = "LONDON"
        sm._current_session = {"allow_new_trades": True}

        # Crypto forbidden on weekday
        allowed, msg = sm.can_trade_symbol("BTCUSD")
        assert allowed is False
        assert "week-end" in msg

        # 5 Majors allowed
        for sym in ["EURUSD", "GBPUSD", "EURGBP", "EURJPY", "USDJPY"]:
            allowed, msg = sm.can_trade_symbol(sym)
            assert allowed is True, f"{sym} should be allowed on weekdays"

        # Commodities allowed
        for sym in ["XAUUSD", "XAGUSD", "XTIUSD", "XBRUSD", "XNGUSD"]:
            allowed, msg = sm.can_trade_symbol(sym)
            assert allowed is True, f"{sym} should be allowed on weekdays"

        # Exotics / other currencies forbidden
        for sym in ["USDCAD", "AUDUSD", "NZDUSD", "GBPJPY", "USDCHF"]:
            allowed, msg = sm.can_trade_symbol(sym)
            assert allowed is False, f"{sym} should be rejected"

    def test_strategy_engine_choppy_rejection_and_rationale(self):
        engine = StrategyEngine()

        # Create dummy dataframe
        n = 100
        df = pd.DataFrame({
            'open': np.linspace(100, 101, n),
            'high': np.linspace(101, 102, n),
            'low': np.linspace(99, 100, n),
            'close': np.linspace(100, 101, n),
            'volume': [1000] * n,
            'ema_21': [100.5] * n,
            'ema_55': [100.0] * n,
            'ema_200': [99.0] * n,
            'rsi': [52.0] * n,
            'adx': [12.0] * n,
            'atr': [1.0] * n,
            'macd': [0.1] * n,
            'macd_signal': [0.1] * n,
            'macd_hist': [0.0] * n,
        })

        # Choppy noise regime must be rejected with rationale
        res = engine.evaluate(df, symbol="EURUSD", regime="choppy_noise", session_name="LONDON")
        assert res.should_long is False and res.should_short is False
        assert "choppy_noise" in res.decision_rationale

    def test_report_generator_full_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rg = ReportGenerator(reports_dir=tmpdir)

            # Record analysis events
            rg.record_analysis_event(
                symbol="XAUUSD",
                regime="bullish_trend",
                strategy="MURPHY_TREND",
                score=8.5,
                score_min=6.0,
                rr=2.4,
                decision="BUY",
                rationale="Tendance haussière claire, EMA21 > EMA55 > EMA200, pullback testé avec succès."
            )

            # Record rejection event
            rg.record_rejection_event(
                symbol="EURUSD",
                reason="Rapport Risque/Rendement insuffisant (R:R 1.45 < 1.8)"
            )

            # Record trade event
            rg.record_trade_event(
                symbol="XAUUSD",
                side="BUY",
                size=0.10,
                entry_price=2380.50,
                sl=2365.00,
                tp=2415.00,
                strategy="MURPHY_TREND",
                rationale="Exécution achat suite à confluence technique H1/M15."
            )

            # Generate daily report
            date_str = "2026-09-08"
            report_content = rg.generate_daily_report(date_str)

            # Check markdown sections
            assert f"Rapport Journalier NexQuant SuperBot — {date_str}" in report_content
            assert "1. Bilan Financier Quotidien" in report_content
            assert "2. Performance des Stratégies" in report_content
            assert "3. Déroulement Détaillé Session par Session" in report_content
            assert "Le Comment et Pourquoi" in report_content
            assert "XAUUSD" in report_content
            assert "MURPHY_TREND" in report_content
            assert "Rapport Risque/Rendement insuffisant" in report_content

            # Check file saved on disk
            report_file = os.path.join(tmpdir, f"report_{date_str}.md")
            assert os.path.exists(report_file)
            with open(report_file, 'r', encoding='utf-8') as f:
                saved = f.read()
                assert len(saved) > 200

