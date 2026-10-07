"""Le garde-fou ALLOW_LIVE_TRADING doit bloquer un compte MT5 réel."""

from types import SimpleNamespace

import pytest

from superbot import orchestrator
from superbot.orchestrator import SuperBot


def test_real_mt5_account_is_blocked_without_allow_live_trading(monkeypatch):
    monkeypatch.setattr(orchestrator, "ALLOW_LIVE_TRADING", False)
    # MT5Client n'expose pas d'attribut `testnet` : seul le type de compte fait foi
    fake_bot = SimpleNamespace(
        running=False,
        broker=SimpleNamespace(get_account_summary=lambda: {"account_type": "MT5_REAL"}),
    )
    with pytest.raises(SystemExit):
        SuperBot.start(fake_bot)
