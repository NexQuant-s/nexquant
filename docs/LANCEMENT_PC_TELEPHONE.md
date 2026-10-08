# Démarrer et piloter NexQuant depuis le PC ou le téléphone

Contrainte de départ : l'API MetaTrader 5 ne fonctionne que sous **Windows, avec le terminal MT5 ouvert
dans une session utilisateur**. Le bot doit donc tourner sur un PC Windows allumé (le vôtre ou un VPS
Windows) ; le téléphone ne peut que le **piloter**, pas l'exécuter.

## 1. PC : prêt à l'emploi (scripts fournis)

| Script | Effet |
|---|---|
| `scripts/start_bot.ps1` | Démarre le bot en arrière-plan (ne fait rien s'il tourne déjà) |
| `scripts/stop_bot.ps1` | Arrête le bot (les positions gardent leurs SL/TP chez le broker) |
| `scripts/install_autostart.ps1` | Lancement automatique à l'ouverture de session + relance en cas d'arrêt + raccourcis Bureau « Démarrer / Arrêter NexQuant » |

Installation (une fois) : `pwsh -ExecutionPolicy Bypass -File scripts\install_autostart.ps1`.
Une seconde instance est impossible : le bot pose un verrou exclusif au démarrage.

## 2. Téléphone : options comparées

| Option | Effort | Sécurité | Verdict |
|---|---|---|---|
| **A. Bot Telegram de pilotage** (`/status`, `/positions`, `/pnl`, `/pause`, `/reprendre`, alertes à chaque trade) | ~1 jour | Bonne : seul votre `chat_id` est autorisé, aucun port ouvert sur le PC | **Recommandé** |
| B. Dashboard existant via **Tailscale** (VPN privé gratuit PC ↔ téléphone) | ~30 min | Bonne (réseau privé chiffré), mais le dashboard n'a pas d'authentification | Bon complément pour consulter les graphiques |
| C. Bureau à distance (Chrome Remote Desktop / AnyDesk) | 10 min | Bonne | Dépannage uniquement (peu pratique au quotidien) |
| D. Application web complète (ancien plan TanStack/Supabase ou FastAPI) | Plusieurs semaines | À construire (auth, API, hébergement) | Abandonnée à juste titre : disproportionnée pour un usage personnel |

## 3. Fonctionnement 24 h/24

Le PC doit rester allumé et connecté (désactiver la mise en veille). Alternative sans PC : un **VPS
Windows** proche des serveurs du broker (plusieurs brokers, dont Fusion Markets, en proposent sous
conditions de volume) ; on y copie le dossier, `.env` compris, et on lance `install_autostart.ps1`.

## Recommandation

1. Maintenant : `install_autostart.ps1` (démarrage automatique + raccourcis).
2. Ensuite : bot Telegram de pilotage et d'alertes (option A), plus Tailscale si vous voulez le dashboard
   sur téléphone (option B). Rester sur `DASHBOARD_HOST=127.0.0.1` sans Tailscale.
