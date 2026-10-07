"""Filtre anti-news : flux ForexFactory (format ISO + 'country') et symboles MT5 sans '/'."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from superbot.news.news_manager import NewsManager


def _manager():
    return NewsManager({
        "NEWS_ASSETS": ["EUR", "USD", "JPY"],
        "NEWS_AVOIDANCE_BEFORE": 30,
        "NEWS_AVOIDANCE_AFTER": 15,
        "NEWS_HIGH_IMPACT_ONLY": True,
    })


def _feed(minutes_from_now: int, country: str = "USD", impact: str = "High"):
    event_time = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-4))) + timedelta(minutes=minutes_from_now)
    return [{"title": "Non-Farm Employment Change", "country": country,
             "date": event_time.isoformat(timespec="seconds"), "impact": impact,
             "forecast": "", "previous": ""}]


def _load(manager, feed, monkeypatch):
    monkeypatch.setattr("superbot.news.news_manager.requests.get",
                        lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: feed))
    manager._update_forex_factory_news()


def test_symbol_currencies_for_mt5_symbols():
    assert NewsManager._symbol_currencies("EURUSD") == ["EUR", "USD"]
    assert NewsManager._symbol_currencies("EUR/USD") == ["EUR", "USD"]
    assert NewsManager._symbol_currencies("XAUUSD") == ["XAU", "USD"]


def test_imminent_usd_news_blocks_eurusd_and_gold(monkeypatch):
    m = _manager()
    _load(m, _feed(minutes_from_now=10), monkeypatch)
    assert m.latest_news[0].currency == "USD"
    assert m.should_avoid_trading_due_to_news("EURUSD")[0] is True
    assert m.should_avoid_trading_due_to_news("XAUUSD")[0] is True


def test_distant_news_does_not_block(monkeypatch):
    m = _manager()
    _load(m, _feed(minutes_from_now=240), monkeypatch)
    assert m.should_avoid_trading_due_to_news("EURUSD")[0] is False


def test_refresh_does_not_duplicate_weekly_events(monkeypatch):
    m = _manager()
    feed = _feed(minutes_from_now=600)
    for _ in range(3):
        m._cache_timestamps.clear()  # forcer le rafraîchissement
        _load(m, feed, monkeypatch)
    assert len(m.latest_news) == 1


def test_holiday_entries_are_ignored(monkeypatch):
    m = _manager()
    m.high_impact_only = False
    _load(m, _feed(minutes_from_now=5, impact="Holiday"), monkeypatch)
    assert m.latest_news == []


def _neutral_sentiment(m):
    from superbot.news.news_manager import SentimentScore
    m.latest_sentiment = SentimentScore(overall=0.0, fear_greed=50, news_impact=0.0, social_media=0.0,
                                        on_chain=0.0, confidence=1.0, timestamp=datetime.now())


def test_future_calendar_events_do_not_reduce_risk(monkeypatch):
    m = _manager()
    _load(m, _feed(minutes_from_now=300) + _feed(minutes_from_now=900), monkeypatch)
    _neutral_sentiment(m)
    assert m.get_recent_high_impact_news(hours=2) == []
    assert m.get_risk_factor() == 1.0


def test_past_high_impact_news_reduces_risk(monkeypatch):
    m = _manager()
    _load(m, _feed(minutes_from_now=-30), monkeypatch)
    _neutral_sentiment(m)
    assert len(m.get_recent_high_impact_news(hours=2)) == 1
    assert abs(m.get_risk_factor() - 0.8) < 1e-9


def test_unrelated_currency_does_not_block(monkeypatch):
    m = _manager()
    _load(m, _feed(minutes_from_now=5, country="JPY"), monkeypatch)
    assert m.should_avoid_trading_due_to_news("EURUSD")[0] is False
    assert m.should_avoid_trading_due_to_news("USDJPY")[0] is True
