"""Contrôleur Telegram et pause à distance : autorisation, commandes, confirmation, alertes."""

import json
from types import SimpleNamespace

import pytest

import superbot.telegram_controller as tc
from superbot.remote_control import apply_remote_pause, read_remote_pause, write_remote_pause


class FakeHttp:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, timeout=None):
        assert "bot" in url
        if url.endswith("/sendMessage"):
            self.sent.append((str(json["chat_id"]), json["text"]))
        return SimpleNamespace(json=lambda: {"ok": True, "result": []})


def _msg(chat_id, text):
    return {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": text}}


@pytest.fixture
def ctl(monkeypatch):
    monkeypatch.setattr(tc, "bot_processes", lambda: [])
    monkeypatch.setattr(tc, "dashboard_data", lambda: None)
    write_remote_pause(False)
    return tc.TelegramController("TOKEN", "42", http=FakeHttp())


def test_unauthorized_chat_is_ignored(ctl):
    ctl.handle(_msg(999, "/arreter"))
    assert ctl.http.sent == []


def test_without_chat_id_only_reveals_the_sender_id(monkeypatch):
    monkeypatch.setattr(tc, "bot_processes", lambda: [])
    write_remote_pause(False)
    c = tc.TelegramController("TOKEN", "", http=FakeHttp())
    c.handle(_msg(777, "/pause"))
    assert c.http.sent and "777" in c.http.sent[0][1]
    assert read_remote_pause() is False  # aucune commande exécutée


def test_pause_and_resume_write_control_file(ctl):
    ctl.handle(_msg(42, "/pause"))
    assert read_remote_pause() is True
    ctl.handle(_msg(42, "/reprendre"))
    assert read_remote_pause() is False


def test_stop_requires_confirmation(ctl, monkeypatch):
    stopped = []
    monkeypatch.setattr(tc, "bot_processes", lambda: [object()])
    monkeypatch.setattr(tc, "stop_bot", lambda: stopped.append(1) or 1)
    ctl.handle(_msg(42, "/confirmer_arret"))
    assert stopped == []
    ctl.handle(_msg(42, "/arreter"))
    ctl.handle(_msg(42, "/confirmer_arret"))
    assert stopped == [1] and ctl.expected_stop


def test_closed_trade_in_journal_triggers_alert(ctl):
    from superbot.config import LOG_DIR
    path = LOG_DIR / "trades_mt5.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    ctl._check_journal()  # premier passage : mémorise la position, pas d'alerte sur l'historique
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"symbol": "EURUSD", "pnl": 1.99, "close_reason": "tp", "status": "closed"}) + "\n")
    ctl._check_journal()
    assert any("EURUSD" in text and "+1.99" in text for _, text in ctl.http.sent)


def test_apply_remote_pause_does_not_override_other_pauses():
    bot = SimpleNamespace(is_paused=True)  # pause pour une autre raison (drift, circuit breaker…)
    write_remote_pause(False)
    apply_remote_pause(bot)
    assert bot.is_paused is True
    write_remote_pause(True)
    apply_remote_pause(bot)
    write_remote_pause(False)
    apply_remote_pause(bot)
    assert bot.is_paused is False and bot._remote_paused is False


def test_poll_once_dispatches_updates_and_advances_offset(monkeypatch):
    """Régression : getUpdates recevait deux fois « timeout » (TypeError) et le contrôleur bouclait en erreur."""
    monkeypatch.setattr(tc, "bot_processes", lambda: [])
    monkeypatch.setattr(tc, "dashboard_data", lambda: None)
    write_remote_pause(False)

    class Http(FakeHttp):
        def post(self, url, json=None, timeout=None):
            if url.endswith("/getUpdates"):
                assert json["timeout"] == 25 and timeout == 35  # attente longue Telegram / délai HTTP
                return SimpleNamespace(json=lambda: {"ok": True, "result": [_msg(42, "/pause") | {"update_id": 7}]})
            return super().post(url, json=json, timeout=timeout)

    c = tc.TelegramController("TOKEN", "42", http=Http())
    c.poll_once()
    assert c.offset == 8 and read_remote_pause() is True
    write_remote_pause(False)
