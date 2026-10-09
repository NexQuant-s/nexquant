"""
Contrôleur Telegram de NexQuant : pilote le bot depuis le téléphone.

Processus SÉPARÉ du bot (il doit survivre à son arrêt pour pouvoir le relancer) :
    python -m superbot.telegram_controller

Commandes : /status /positions /pause /reprendre /demarrer /arreter (+ /confirmer_arret) /aide
Alertes   : ouverture et clôture de positions, arrêt inattendu du bot.
Sécurité  : seul TELEGRAM_CHAT_ID est obéi ; aucun port ouvert (long polling sortant vers Telegram) ;
            le jeton n'apparaît jamais dans les logs (les erreurs réseau sont journalisées par type seulement).
"""
import json
import logging
import os
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil
import requests

ROOT = Path(__file__).resolve().parents[1]
log = logging.getLogger("telegram_controller")

HELP = (
    "🤖 NexQuant — commandes\n"
    "/status — état du bot, solde, P&L du jour\n"
    "/positions — positions ouvertes\n"
    "/pause — plus de nouveaux ordres (positions gardées avec SL/TP)\n"
    "/reprendre — réactive les nouveaux ordres\n"
    "/demarrer — lance le bot\n"
    "/arreter — arrête le bot (confirmation demandée)\n"
    "/aide — cette aide"
)
STOP_CONFIRM_WINDOW = 60  # secondes pour confirmer /arreter


def bot_processes():
    procs = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (p.info.get("name") or "").lower()
            cmd = " ".join(p.info.get("cmdline") or [])
            if name.startswith("python") and "superbot.main" in cmd:
                procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


def start_bot():
    flags = 0
    if os.name == "nt":  # détaché : survit au contrôleur, sans fenêtre
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, "-m", "superbot.main"], cwd=str(ROOT), creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)


def stop_bot() -> int:
    procs = bot_processes()
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(procs, timeout=15)
    for p in alive:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass
    return len(procs)


def dashboard_data():
    port = os.getenv("DASHBOARD_PORT", "5000")
    try:
        return requests.get(f"http://127.0.0.1:{port}/api/data", timeout=5).json()
    except (requests.RequestException, ValueError):
        return None


class TelegramController:
    def __init__(self, token: str, chat_id: str, http=requests):
        self.token = token
        self.chat_id = str(chat_id or "").strip()
        self.http = http
        self.offset = None
        self.pending_stop_at = 0.0
        self.expected_stop = False
        self.was_running = bool(bot_processes())
        self.known_positions = set()
        self.journal_pos = None

    # ── API Telegram ─────────────────────────────────────────────────────────
    def _call(self, method: str, http_timeout: float = 15, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        try:
            r = self.http.post(url, json=params, timeout=http_timeout)
            data = r.json()
            return data.get("result") if data.get("ok") else None
        except Exception as exc:  # jamais le message brut : il contient l'URL, donc le jeton
            log.warning(f"Appel Telegram '{method}' en échec : {type(exc).__name__}")
            return None

    def send(self, text: str, chat_id: str = None):
        target = chat_id or self.chat_id
        if target:
            self._call("sendMessage", chat_id=target, text=text[:4000])

    def poll_once(self):
        params = {"timeout": 25, "allowed_updates": ["message"]}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._call("getUpdates", http_timeout=35, **params) or []
        for upd in updates:
            self.offset = upd["update_id"] + 1
            self.handle(upd)

    # ── Commandes ────────────────────────────────────────────────────────────
    def handle(self, update: dict):
        msg = update.get("message") or {}
        sender = str((msg.get("chat") or {}).get("id", ""))
        text = (msg.get("text") or "").strip()
        if not sender or not text:
            return
        if not self.chat_id:
            self.send(f"Votre chat_id est {sender}. Ajoutez TELEGRAM_CHAT_ID={sender} au .env puis relancez "
                      "le contrôleur. Aucune commande n'est exécutée tant que ce n'est pas fait.", chat_id=sender)
            return
        if sender != self.chat_id:
            log.warning(f"Message ignoré d'un chat non autorisé ({sender}).")
            return
        cmd = text.split()[0].split("@")[0].lower()
        handler = {
            "/start": self.cmd_help, "/aide": self.cmd_help, "/help": self.cmd_help,
            "/status": self.cmd_status, "/positions": self.cmd_positions,
            "/pause": self.cmd_pause, "/reprendre": self.cmd_resume,
            "/demarrer": self.cmd_start, "/arreter": self.cmd_stop, "/confirmer_arret": self.cmd_confirm_stop,
        }.get(cmd)
        log.info(f"Commande reçue : {cmd}")
        self.send(handler() if handler else "Commande inconnue.\n\n" + HELP)

    def cmd_help(self):
        return HELP

    def cmd_status(self):
        from superbot.remote_control import read_remote_pause
        procs = bot_processes()
        lines = [f"Bot : {'🟢 en marche (PID ' + ', '.join(str(p.pid) for p in procs) + ')' if procs else '🔴 arrêté'}",
                 f"Trading : {'⏸️ en pause' if read_remote_pause() else '▶️ actif'}"]
        d = dashboard_data() if procs else None
        if d:
            perf = d.get("performance", {})
            lines.append(f"Solde : {perf.get('current_balance')} € | P&L session : {float(perf.get('total_pnl') or 0):+.2f} €")
            lines.append(f"Positions ouvertes : {len(d.get('positions') or {})}")
        return "\n".join(lines)

    def cmd_positions(self):
        d = dashboard_data()
        if d is None:
            return "Données indisponibles (bot arrêté ou dashboard injoignable)."
        pos = d.get("positions") or {}
        if not pos:
            return "Aucune position ouverte."
        return "\n".join(f"{sym} {str(p.get('side', '')).upper()} entrée {p.get('entry_price')} "
                         f"SL {p.get('stop_loss')} TP {p.get('take_profit')}" for sym, p in pos.items())

    def cmd_pause(self):
        from superbot.remote_control import write_remote_pause
        write_remote_pause(True)
        note = "" if bot_processes() else " (le bot est arrêté : la pause s'appliquera au prochain démarrage)"
        return "⏸️ Pause activée : plus de nouveaux ordres, les positions gardent leurs SL/TP." + note

    def cmd_resume(self):
        from superbot.remote_control import write_remote_pause
        write_remote_pause(False)
        return "▶️ Trading réactivé." + ("" if bot_processes() else " (le bot est arrêté : /demarrer pour le lancer)")

    def cmd_start(self):
        from superbot.remote_control import set_user_stop
        set_user_stop(False)
        if bot_processes():
            return "Le bot tourne déjà."
        start_bot()
        self.expected_stop = False
        for _ in range(20):
            time.sleep(1)
            if bot_processes():
                self.was_running = True
                return "🟢 Bot démarré."
        return "⚠️ Le bot ne semble pas avoir démarré : vérifiez superbot/logs/superbot_mt5.log."

    def cmd_stop(self):
        if not bot_processes():
            return "Le bot est déjà arrêté."
        self.pending_stop_at = time.time()
        return f"Confirmez l'arrêt avec /confirmer_arret dans les {STOP_CONFIRM_WINDOW} s."

    def cmd_confirm_stop(self):
        if time.time() - self.pending_stop_at > STOP_CONFIRM_WINDOW:
            return "Aucun arrêt en attente (envoyez d'abord /arreter)."
        self.pending_stop_at = 0.0
        self.expected_stop = True
        from superbot.remote_control import set_user_stop
        set_user_stop(True)  # le relais de 5 min ne doit pas relancer un arrêt voulu
        n = stop_bot()
        self.was_running = False
        return (f"🔴 Bot arrêté ({n} processus) et relance automatique suspendue. Les positions ouvertes gardent leurs SL/TP "
                "chez le broker. /demarrer pour relancer.")

    # ── Surveillance et alertes ──────────────────────────────────────────────
    def check_alerts(self):
        running = bool(bot_processes())
        if self.was_running and not running and not self.expected_stop:
            self.send("🚨 Le bot s'est arrêté de façon inattendue. /demarrer pour le relancer.")
        self.was_running = running
        if running:
            d = dashboard_data()
            if d is not None:
                current = set((d.get("positions") or {}).keys())
                for sym in current - self.known_positions:
                    p = d["positions"][sym]
                    self.send(f"📈 Position ouverte : {sym} {str(p.get('side', '')).upper()} @ {p.get('entry_price')} "
                              f"| SL {p.get('stop_loss')} | TP {p.get('take_profit')}")
                self.known_positions = current
        self._check_journal()

    def _check_journal(self):
        from superbot.config import LOG_DIR
        path = Path(LOG_DIR) / "trades_mt5.jsonl"
        try:
            size = path.stat().st_size
        except OSError:
            return
        if self.journal_pos is None or size < self.journal_pos:  # premier passage ou fichier recréé
            self.journal_pos = size
            return
        if size == self.journal_pos:
            return
        with path.open("r", encoding="utf-8", errors="replace") as f:
            f.seek(self.journal_pos)
            chunk = f.read()
            self.journal_pos = f.tell()
        for line in chunk.splitlines():
            try:
                t = json.loads(line)
            except ValueError:
                continue
            if t.get("status", "closed") == "closed" and t.get("pnl") is not None:
                pnl = float(t["pnl"])
                self.send(f"{'✅' if pnl >= 0 else '❌'} Position fermée : {t.get('symbol')} {pnl:+.2f} € "
                          f"({t.get('close_reason', '?')})")

    def run(self):
        log.info("Contrôleur Telegram démarré.")
        if self.chat_id:
            self.send("🤖 Contrôleur NexQuant en ligne.\n\n" + HELP)
        while True:
            try:
                self.poll_once()
                self.check_alerts()
            except Exception as exc:
                log.error(f"Boucle du contrôleur : {type(exc).__name__}")
                time.sleep(10)


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    from superbot.config import LOG_DIR
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(Path(LOG_DIR) / "telegram_controller.log", maxBytes=1_000_000,
                                  backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler],
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for noisy in ("urllib3", "requests"):  # leurs logs DEBUG contiendraient l'URL avec le jeton
        logging.getLogger(noisy).setLevel(logging.WARNING)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN manquant dans le .env (créez un bot avec @BotFather).")
        sys.exit(1)
    from superbot.main import _acquire_single_instance_lock
    lock = _acquire_single_instance_lock("telegram")
    if lock is None:
        print("Le contrôleur Telegram tourne déjà.")
        sys.exit(1)
    TelegramController(token, os.getenv("TELEGRAM_CHAT_ID", "")).run()


if __name__ == "__main__":
    main()
