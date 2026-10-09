"""
Gestionnaire « swing » D1 : exécute le pullback de tendance (superbot/strategy/trend_pullback_d1.py) sur les indices
et l'ETH, EN PARALLÈLE du bot H1 (magic number distinct, aucune interférence : le bot H1 ne synchronise que ses
propres instruments).

Un passage = idempotent (état dans LOG_DIR/swing_state.json) ; lancé toutes les heures par le Planificateur de tâches :
    python -m superbot.swing_runner
Activation : SWING_ENABLED=true dans le .env. Pause : /pause Telegram (plus aucune entrée, les stops suiveurs continuent).
"""
import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List

import pandas as pd

from superbot.strategy import trend_pullback_d1 as strat

log = logging.getLogger("swing_runner")
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOLS = "US500,NAS100,US30,JPN225,UK100,EUSTX50,FRA40,AUS200,ETHUSD"


@dataclass
class SwingConfig:
    symbols: List[str] = field(default_factory=lambda: DEFAULT_SYMBOLS.split(","))
    risk_pct: float = 0.5               # % du solde risqué par trade (stop initial)
    max_positions: int = 3              # indices très corrélés : plafond de positions simultanées
    magic: int = 20201
    min_lot_max_risk_pct: float = 1.0   # si le lot minimum dépasse le risque cible : accepté jusqu'à ce % du solde
    max_entry_delay_h: float = 8.0      # un signal n'est plus exécuté plus de 8 h après la clôture de la bougie
    min_age_h: float = 1.0              # pas d'entrée dans l'heure qui suit la clôture (rollover, spreads larges)
    max_spread_frac: float = 0.10       # spread max = 10 % de la distance du stop
    daily_loss_pct: float = 2.0         # plus d'entrée si la perte latente dépasse ce % du solde
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "SwingConfig":
        g = os.environ.get
        return cls(symbols=[s.strip() for s in g("SWING_SYMBOLS", DEFAULT_SYMBOLS).split(",") if s.strip()],
                   risk_pct=float(g("SWING_RISK_PCT", "0.5")), max_positions=int(g("SWING_MAX_POSITIONS", "3")),
                   magic=int(g("SWING_MAGIC", "20201")), enabled=g("SWING_ENABLED", "false").lower() == "true",
                   daily_loss_pct=float(g("MAX_DAILY_LOSS_PCT", "2.0")))


# ── état persistant ──────────────────────────────────────────────────────────────
def state_path() -> Path:
    from superbot.config import LOG_DIR
    return Path(LOG_DIR) / "swing_state.json"


def load_state(path: Path) -> dict:
    try:
        st = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    st.setdefault("positions", {})
    st.setdefault("processed", {})
    return st


def save_state(path: Path, st: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def journal(path: Path, entry: dict) -> None:
    with (path.parent / "swing_trades.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def telegram_notify(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text[:4000]}, timeout=10)
    except Exception as exc:  # le message d'erreur contiendrait l'URL, donc le jeton
        log.warning(f"Notification Telegram impossible : {type(exc).__name__}")


# ── cœur : un passage ────────────────────────────────────────────────────────────
def _floor_step(x: float, step: float) -> float:
    return round(math.floor(x / step + 1e-9) * step, 8) if step > 0 else x


def run_once(ad, cfg: SwingConfig, path: Path, notify=lambda t: None, paused: bool = False,
             p: strat.SwingParams = strat.DEFAULT_PARAMS) -> dict:
    st = load_state(path)
    positions = {x["symbol"]: x for x in ad.positions(cfg.magic)}
    balance, equity = ad.account()
    summary = {"opened": [], "closed": [], "trailed": []}
    for symbol in cfg.symbols:
        try:
            _process(ad, cfg, path, st, positions, balance, equity, symbol, notify, paused, p, summary)
        except Exception as exc:  # un symbole en échec ne doit jamais bloquer les autres (ni les stops suiveurs)
            log.error(f"[{symbol}] erreur : {type(exc).__name__}: {exc}")
    save_state(path, st)
    return summary


def _record_close(ad, path, st, symbol, side, ticket, reason, notify, summary):
    st["positions"].pop(symbol, None)
    pnl = ad.closed_pnl(ticket)
    journal(path, {"timestamp": datetime.now(timezone.utc).isoformat(), "symbol": symbol, "side": side,
                   "pnl": pnl, "close_reason": reason, "ticket": ticket})
    label = {"stop": "fermé par le stop", "time": "fermé (délai atteint)", "trailing": "fermé (stop suiveur)"}[reason]
    notify(f"{'✅' if (pnl or 0) >= 0 else '❌'} Swing {symbol} {label} : {pnl if pnl is not None else '?'} €")
    summary["closed"].append(symbol)


def _process(ad, cfg, path, st, positions, balance, equity, symbol, notify, paused, p, summary):
    bars = ad.d1_bars(symbol, 400)
    if bars is None or len(bars) < strat.MIN_BARS:
        log.info(f"[{symbol}] historique D1 insuffisant : ignoré")
        return
    last_date = str(bars.index[-1].date())
    pos, known = positions.get(symbol), st["positions"].get(symbol)

    if known and not pos:  # position fermée par le broker (stop touché)
        _record_close(ad, path, st, symbol, known["side"], known["ticket"], "stop", notify, summary)
        known = None
    if pos and not known:  # état perdu : on adopte la position avec les paramètres par défaut
        a = float(strat.atr(bars, p.atr_len).iloc[-1])
        known = st["positions"][symbol] = {"ticket": pos["ticket"], "side": pos["side"], "signal_date": last_date,
                                           "entry_price": pos["price"], "atr": a, "sl": pos["sl"], "lots": pos["lots"]}
        log.warning(f"[{symbol}] position {pos['ticket']} adoptée (état absent)")

    # ── gestion d'une position ouverte (une fois par nouvelle bougie) ──
    if pos:
        if st["processed"].get(symbol) == last_date:
            return
        st["processed"][symbol] = last_date
        since = bars[bars.index > pd.Timestamp(known["signal_date"])]
        if len(since) >= p.max_bars:
            ad.close(symbol, pos)
            _record_close(ad, path, st, symbol, known["side"], pos["ticket"], "time", notify, summary)
            return
        cur_sl = pos["sl"] or known["sl"]
        new_sl = strat.trailing_stop(known["side"], known["entry_price"], since, known["atr"], cur_sl, p)
        spec = ad.spec(symbol)
        if abs(new_sl - cur_sl) >= spec["tick_size"]:
            bid, ask, _ = ad.tick(symbol)
            crossed = new_sl >= bid if known["side"] == "LONG" else new_sl <= ask
            if crossed:  # le prix est déjà au-delà du stop suiveur : sortie au marché
                ad.close(symbol, pos)
                _record_close(ad, path, st, symbol, known["side"], pos["ticket"], "trailing", notify, summary)
            elif ad.set_sl(pos["ticket"], symbol, round(new_sl, spec["digits"])):
                known["sl"] = new_sl
                summary["trailed"].append(symbol)
                log.info(f"[{symbol}] stop suiveur {cur_sl:.5g} → {new_sl:.5g}")
        return

    # ── recherche d'une entrée (une fois par nouvelle bougie, sauf report transitoire) ──
    if st["processed"].get(symbol) == last_date:
        return
    sig = strat.evaluate(bars, p)
    if sig is None:
        st["processed"][symbol] = last_date
        return
    now = ad.server_now(symbol)
    age_h = (now - (bars.index[-1] + pd.Timedelta(days=1))).total_seconds() / 3600
    if age_h > cfg.max_entry_delay_h:
        st["processed"][symbol] = last_date
        log.info(f"[{symbol}] signal {sig['side']} périmé ({age_h:.1f} h après la clôture) : ignoré")
        return
    if age_h < cfg.min_age_h:
        return  # trop tôt (rollover) : nouvel essai au prochain passage
    if paused:
        log.info(f"[{symbol}] signal {sig['side']} ignoré : trading en pause")
        return
    if len(positions) + len(summary["opened"]) >= cfg.max_positions:
        log.info(f"[{symbol}] signal {sig['side']} reporté : {cfg.max_positions} positions swing déjà ouvertes")
        return
    if balance > 0 and (equity - balance) / balance * 100 <= -cfg.daily_loss_pct:
        log.warning(f"[{symbol}] signal ignoré : perte latente au-delà de {cfg.daily_loss_pct}% du solde")
        return

    spec, (bid, ask, _) = ad.spec(symbol), ad.tick(symbol)
    entry = ask if sig["side"] == "LONG" else bid
    stop_dist = p.sl_atr * sig["atr"]
    if (ask - bid) > cfg.max_spread_frac * stop_dist:
        log.info(f"[{symbol}] spread trop large ({ask - bid:.5g} > {cfg.max_spread_frac:.0%} du stop) : nouvel essai plus tard")
        return
    if stop_dist <= spec["stops_level_price"] * 1.5:
        st["processed"][symbol] = last_date
        return
    loss_per_lot = stop_dist / spec["tick_size"] * spec["tick_value"]
    lots = _floor_step(balance * cfg.risk_pct / 100 / loss_per_lot, spec["vstep"])
    if lots < spec["vmin"]:
        if spec["vmin"] * loss_per_lot <= balance * cfg.min_lot_max_risk_pct / 100:
            lots = spec["vmin"]
        else:
            st["processed"][symbol] = last_date
            log.info(f"[{symbol}] ignoré : le lot minimum risque {spec['vmin'] * loss_per_lot:.1f} € "
                     f"(> {cfg.min_lot_max_risk_pct}% du solde)")
            return
    lots = min(lots, spec["vmax"])
    sl = round(entry - stop_dist if sig["side"] == "LONG" else entry + stop_dist, spec["digits"])
    ok, ticket, price, msg = ad.open(symbol, sig["side"], lots, sl, cfg.magic, "swing_d1")
    if not ok:
        log.error(f"[{symbol}] ordre refusé : {msg}")
        return
    st["positions"][symbol] = {"ticket": ticket, "side": sig["side"], "signal_date": last_date, "entry_price": price,
                               "atr": sig["atr"], "sl": sl, "lots": lots}
    st["processed"][symbol] = last_date
    summary["opened"].append(symbol)
    risk_eur = lots * loss_per_lot
    notify(f"📈 Swing {symbol} {sig['side']} {lots} lot @ {price} | SL {sl} | risque {risk_eur:.1f} € ({risk_eur / balance * 100:.2f} %)")
    log.info(f"[{symbol}] {sig['side']} {lots} lot @ {price} SL {sl} (risque {risk_eur:.2f} €)")


# ── adaptateur MetaTrader 5 ──────────────────────────────────────────────────────
class MT5Adapter:
    def __init__(self):
        import MetaTrader5 as mt5
        from superbot.broker.mt5_client import MT5Client
        self.mt5 = mt5
        self.client = MT5Client()  # connexion et identifiants via le .env

    def d1_bars(self, symbol, n=400):
        self.mt5.symbol_select(symbol, True)
        r = self.mt5.copy_rates_from_pos(symbol, self.mt5.TIMEFRAME_D1, 0, n)
        if r is None or len(r) < 2:
            return None
        df = pd.DataFrame(r)
        df.index = pd.to_datetime(df["time"], unit="s")
        return df[["open", "high", "low", "close"]].iloc[:-1]  # la dernière bougie est en formation

    def tick(self, symbol):
        t = self.mt5.symbol_info_tick(symbol)
        return t.bid, t.ask, t.time

    def server_now(self, symbol):
        return pd.Timestamp(self.mt5.symbol_info_tick(symbol).time, unit="s")

    def spec(self, symbol):
        i = self.mt5.symbol_info(symbol)
        return dict(vmin=i.volume_min, vstep=i.volume_step, vmax=i.volume_max, tick_size=i.trade_tick_size,
                    tick_value=i.trade_tick_value, digits=i.digits, stops_level_price=i.trade_stops_level * i.point)

    def account(self):
        a = self.mt5.account_info()
        return a.balance, a.equity

    def positions(self, magic):
        out = []
        for p in self.mt5.positions_get() or []:
            if p.magic == magic:
                out.append(dict(symbol=p.symbol, ticket=p.ticket, side="LONG" if p.type == self.mt5.POSITION_TYPE_BUY else "SHORT",
                                lots=p.volume, price=p.price_open, sl=p.sl, tp=p.tp, magic=p.magic))
        return out

    def open(self, symbol, side, lots, sl, magic, comment):
        m = self.mt5
        t = m.symbol_info_tick(symbol)
        req = {"action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": lots,
               "type": m.ORDER_TYPE_BUY if side == "LONG" else m.ORDER_TYPE_SELL,
               "price": t.ask if side == "LONG" else t.bid, "sl": sl, "tp": 0.0, "deviation": 30, "magic": magic,
               "comment": comment, "type_time": m.ORDER_TIME_GTC, "type_filling": self.client._resolve_filling_mode(symbol)}
        chk = m.order_check(req)
        if chk is None or chk.retcode not in (0, m.TRADE_RETCODE_DONE):
            return False, None, None, f"order_check: {getattr(chk, 'retcode', m.last_error())} {getattr(chk, 'comment', '')}"
        res = m.order_send(req)
        if res is None or res.retcode != m.TRADE_RETCODE_DONE:
            return False, None, None, f"order_send: {getattr(res, 'retcode', m.last_error())} {getattr(res, 'comment', '')}"
        ticket = next((p.ticket for p in m.positions_get(symbol=symbol) or [] if p.magic == magic), res.order)
        return True, ticket, res.price or req["price"], ""

    def set_sl(self, ticket, symbol, sl):
        m = self.mt5
        pos = next((p for p in m.positions_get(symbol=symbol) or [] if p.ticket == ticket), None)
        if pos is None:
            return False
        res = m.order_send({"action": m.TRADE_ACTION_SLTP, "position": ticket, "symbol": symbol, "sl": sl, "tp": pos.tp})
        return res is not None and res.retcode == m.TRADE_RETCODE_DONE

    def close(self, symbol, pos):
        m = self.mt5
        t = m.symbol_info_tick(symbol)
        long = pos["side"] == "LONG"
        res = m.order_send({"action": m.TRADE_ACTION_DEAL, "symbol": symbol, "volume": pos["lots"], "position": pos["ticket"],
                            "type": m.ORDER_TYPE_SELL if long else m.ORDER_TYPE_BUY, "price": t.bid if long else t.ask,
                            "deviation": 30, "magic": pos["magic"], "comment": "swing_close", "type_time": m.ORDER_TIME_GTC,
                            "type_filling": self.client._resolve_filling_mode(symbol)})
        return res is not None and res.retcode == m.TRADE_RETCODE_DONE

    def closed_pnl(self, ticket):
        deals = self.mt5.history_deals_get(position=int(ticket))
        if not deals:
            return None
        return round(sum(d.profit + d.commission + d.swap + d.fee for d in deals), 2)


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from superbot.config import LOG_DIR
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                        handlers=[RotatingFileHandler(Path(LOG_DIR) / "swing_runner.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])
    cfg = SwingConfig.from_env()
    if not cfg.enabled:
        print("SWING_ENABLED=false : rien à faire.")
        return
    from superbot.main import _acquire_single_instance_lock
    lock = _acquire_single_instance_lock("swing")
    if lock is None:
        print("Un passage swing est déjà en cours.")
        return
    from superbot.remote_control import read_remote_pause
    summary = run_once(MT5Adapter(), cfg, state_path(), notify=telegram_notify, paused=read_remote_pause())
    log.info(f"Passage terminé : {summary}")


if __name__ == "__main__":
    main()
