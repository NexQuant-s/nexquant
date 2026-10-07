"""
🧠 NexQuant V3 — Report Generator
Génère chaque jour à 22:30 UTC un rapport journalier complet en Markdown.
- Performance par stratégie, régime, instrument
- Apprentissages du jour (décisions autonomes)
- Ajustements pour la prochaine session
- Sauvegarde en DB + fichier Markdown local
"""
import os
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

log = logging.getLogger("brain.report_generator")


class ReportGenerator:
    """
    Génère des rapports journaliers NexQuant V3.
    Peut être déclenché manuellement ou via timer à 22:30 UTC.
    """

    REPORTS_DIR = "reports"

    def __init__(self, db=None, session_manager=None, strategy_engine=None,
                 performance_learner=None, knowledge_feeder=None, bot=None, reports_dir=None):
        self.db = db
        self.session_manager = session_manager
        self.strategy_engine = strategy_engine
        self.performance_learner = performance_learner
        self.knowledge_feeder = knowledge_feeder
        self.bot = bot
        if not reports_dir:
            from superbot.config import REPORTS_DIR
            reports_dir = REPORTS_DIR
        self.REPORTS_DIR = reports_dir
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.RLock()

        # Mémoire des sessions du jour courant : date_str -> list of session_dict
        self._sessions_log: Dict[str, List[Dict[str, Any]]] = {}
        # Événements en cours dans la session active
        self._current_session_events: Dict[str, Any] = {
            'trades': [],
            'rejected': [],
            'analyses': [],
            'post_mortems': [],
        }

        os.makedirs(self.REPORTS_DIR, exist_ok=True)
        log.info("ReportGenerator détaillé multi-sessions initialisé")

    def record_analysis_event(
        self,
        symbol: str,
        regime: str = "unknown",
        strategy: str = "none",
        rationale: str = "",
        rr: float = 0.0,
        score: float = 0.0,
        score_min: float = 6.0,
        decision: str = "NO_SIGNAL",
        **kwargs
    ):
        """Enregistre une analyse pré-trade approfondie pour le rapport de session."""
        with self._lock:
            now_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
            self._current_session_events['analyses'].append({
                'time': now_str,
                'symbol': symbol,
                'regime': regime,
                'strategy': strategy,
                'score': score,
                'score_min': score_min,
                'rr': rr,
                'decision': decision,
                'rationale': rationale
            })
            if len(self._current_session_events['analyses']) > 100:
                self._current_session_events['analyses'] = self._current_session_events['analyses'][-100:]

    def record_trade_event(
        self,
        trade_data: Optional[Dict[str, Any]] = None,
        decision_rationale: str = "",
        symbol: str = "",
        side: str = "",
        size: float = 0.0,
        entry_price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        strategy: str = "",
        rationale: str = "",
        **kwargs
    ):
        """Enregistre un ordre exécuté avec son explication décisionnelle."""
        with self._lock:
            now_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
            trade_entry = dict(trade_data) if trade_data else {}
            if symbol:
                trade_entry['symbol'] = symbol
            if side:
                trade_entry['side'] = side
            if size:
                trade_entry['size'] = size
            if entry_price:
                trade_entry['entry_price'] = entry_price
            if sl:
                trade_entry['sl'] = sl
            if tp:
                trade_entry['tp'] = tp
            if strategy:
                trade_entry['strategy'] = strategy
            trade_entry['time'] = now_str
            trade_entry['decision_rationale'] = rationale or decision_rationale or trade_entry.get('decision_rationale', '')
            self._current_session_events['trades'].append(trade_entry)

        try:
            self.generate_daily_report()
        except Exception as e:
            log.debug(f"Erreur mise à jour rapport post-trade: {e}")

    def record_rejection_event(self, symbol: str, reason: str, strategy_name: str = "NONE", details: Optional[Dict[str, Any]] = None):
        """Enregistre une opportunité filtrée / évitée et le motif."""
        with self._lock:
            now_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
            self._current_session_events['rejected'].append({
                'time': now_str,
                'symbol': symbol,
                'strategy': strategy_name,
                'reason': reason,
                'details': details or {}
            })
            if len(self._current_session_events['rejected']) > 100:
                self._current_session_events['rejected'] = self._current_session_events['rejected'][-100:]

    def record_post_mortem_event(
        self,
        symbol: str,
        consecutive_losses: int,
        cause: str,
        adapted_parameters: Optional[Dict[str, Any]] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Enregistre un diagnostic post-mortem suite à un enchaînement de pertes et la pause de 10 min."""
        with self._lock:
            now_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
            self._current_session_events.setdefault('post_mortems', []).append({
                'time': now_str,
                'symbol': symbol,
                'consecutive_losses': consecutive_losses,
                'cause': cause,
                'adapted_parameters': adapted_parameters or {},
                'details': details or {}
            })
            if len(self._current_session_events['post_mortems']) > 50:
                self._current_session_events['post_mortems'] = self._current_session_events['post_mortems'][-50:]

        try:
            self.generate_daily_report()
        except Exception as e:
            log.debug(f"Erreur mise à jour rapport post-mortem: {e}")

    def record_session_transition(self, old_session: str, new_session: str, session_pnl: float = 0.0, trades_count: int = 0):
        """
        Appelé à la clôture d'une session : archive le bilan de la session écoulée
        et regénère le rapport du jour.
        """
        now_utc = datetime.now(timezone.utc)
        date_str = now_utc.strftime('%Y-%m-%d')

        with self._lock:
            if date_str not in self._sessions_log:
                self._sessions_log[date_str] = []

            completed_session = {
                'name': old_session or 'INIT',
                'closed_at': now_utc.strftime('%H:%M UTC'),
                'pnl': session_pnl,
                'trades_count': trades_count,
                'trades': list(self._current_session_events.get('trades', [])),
                'rejected': list(self._current_session_events.get('rejected', [])),
                'analyses': list(self._current_session_events.get('analyses', [])),
                'post_mortems': list(self._current_session_events.get('post_mortems', [])),
            }
            self._sessions_log[date_str].append(completed_session)

            self._current_session_events = {
                'trades': [],
                'rejected': [],
                'analyses': [],
                'post_mortems': [],
            }

        log.info(f"📝 Bilan archivé pour la session {old_session} ({trades_count} trades, PnL={session_pnl:+.2f}€).")
        try:
            self.generate_daily_report()
        except Exception as e:
            log.warning(f"Erreur mise à jour rapport post-session: {e}")

    def generate_daily_report(self, target_date: Optional[Any] = None, force: bool = False) -> str:
        """
        Génère ou met à jour le rapport journalier Markdown complet `reports/report_YYYY-MM-DD.md`.
        Détaille chaque session de la journée avec le Pourquoi et Comment des décisions.
        """
        if isinstance(target_date, bool):
            # Compatibilité : ancien appel generate_daily_report(True)
            target_date = None

        now_utc = datetime.now(timezone.utc)
        date_str = target_date if isinstance(target_date, str) else now_utc.strftime('%Y-%m-%d')
        time_str = now_utc.strftime('%H:%M UTC')

        lines = []
        lines.append(f"# 📊 Rapport Journalier NexQuant SuperBot — {date_str}")
        lines.append(f"*Dernière mise à jour : {date_str} à {time_str}*")
        lines.append("")

        # ── 1. BILAN FINANCIER QUOTIDIEN ──────────────────────────────────────
        lines.append("## 🎯 1. Bilan Financier Quotidien")
        target = 200.0
        achieved = 0.0
        balance_start = 0.0
        balance_end = 0.0
        pct = 0.0

        if self.session_manager:
            try:
                progress = self.session_manager.get_daily_progress()
                achieved = float(progress.get('achieved_eur', 0.0))
                target = float(progress.get('target_eur', 200.0))
                balance_start = float(progress.get('balance_start', 0.0))
                balance_end = balance_start + achieved
                pct = float(progress.get('achievement_pct', 0.0))
            except Exception as _exc:
                log.debug(f"Erreur ignorée (non bloquante) : {_exc}")
        elif self.bot:
            balance_end = getattr(self.bot, '_cached_balance', 0.0)
            balance_start = getattr(self.bot, 'initial_balance', balance_end)
            achieved = balance_end - balance_start
            pct = (achieved / target * 100) if target > 0 else 0.0

        status = "✅ Objectif Journalier Atteint !" if pct >= 100 else (f"⏳ Progression : {pct:.1f}% de l'objectif" if achieved > 0 else ("⏸️ Aucun trade" if achieved == 0 else "⚠️ Session en retrait"))

        lines.append("| Métrique | Valeur |")
        lines.append("|---|---|")
        lines.append("| **Cible Capital Session (Visée)** | **35.00 € à 40.00 €** |")
        lines.append(f"| **Objectif Gain PnL** | {target:.2f} € |")
        lines.append(f"| **PnL Réalisé Jour** | **{achieved:+.2f} €** ({pct:.1f}%) |")
        lines.append(f"| **Solde Début Jour** | {balance_start:.2f} € |")
        lines.append(f"| **Solde Actuel / Fin** | {balance_end:.2f} € |")
        target_tracker = getattr(self, 'session_target_tracker', None)
        if not target_tracker and hasattr(self, 'session_manager') and hasattr(self.session_manager, 'bot_instance'):
            target_tracker = getattr(self.session_manager.bot_instance, 'session_target_tracker', None)
        if target_tracker:
            t_status = target_tracker.get_status()
            lines.append(f"| **Progression vers la Cible** | **{t_status['progress_pct']:.1f} %** (Reste : {t_status['remaining_amount']:.2f} €) |")
            if t_status['current_equity'] > 0:
                lines.append(f"| **Équité en Direct** | {t_status['current_equity']:.2f} € (Pic : {t_status['peak_equity']:.2f} €) |")
        lines.append(f"| **Statut de Performance** | {status} |")
        lines.append("")

        # ── 2. PERFORMANCE PAR STRATÉGIE ──────────────────────────────────────
        lines.append("## ♟️ 2. Performance des Stratégies d'Élite")
        if self.strategy_engine:
            try:
                lb = self.strategy_engine.get_strategy_leaderboard()
                if lb:
                    lines.append("| Stratégie | Trades | Win Rate | PnL Total |")
                    lines.append("|---|---|---|---|")
                    for item in lb:
                        wr = f"{item.get('win_rate', item.get('wr', 0))*100:.1f}%"
                        pnl_strat = item.get('pnl', 0.0)
                        lines.append(f"| **{item.get('name', item.get('strategy', '—'))}** | {item.get('trades', 0)} | {wr} | {pnl_strat:+.2f} € |")
                else:
                    lines.append("*Aucune statistique de stratégie enregistrée aujourd'hui.*")
            except Exception as e:
                lines.append(f"*Données stratégies indisponibles : {e}*")
        else:
            lines.append("*StrategyEngine non disponible*")
        lines.append("")

        # ── 3. DÉROULEMENT DÉTAILLÉ SESSION PAR SESSION ────────────────────────
        lines.append("## 🏛️ 3. Déroulement Détaillé Session par Session")
        lines.append("> Ce journal retrace chaque session de la journée : contextes analysés, stratégies sélectionnées et motifs de chaque décision (Le Comment et Pourquoi).")
        lines.append("")

        with self._lock:
            recorded_sessions = list(self._sessions_log.get(date_str, []))
            curr_sess_name = self.session_manager.get_current_session().get('name', 'EN COURS') if self.session_manager else 'EN COURS'
            curr_sess_pnl = self.session_manager.get_current_session().get('pnl_session', 0.0) if self.session_manager else 0.0
            curr_sess_trades = self.session_manager.get_current_session().get('trades_count', 0) if self.session_manager else len(self._current_session_events['trades'])

            active_session_view = {
                'name': f"{curr_sess_name} *(En cours)*",
                'closed_at': f"Depuis {time_str}",
                'pnl': curr_sess_pnl,
                'trades_count': curr_sess_trades,
                'trades': list(self._current_session_events.get('trades', [])),
                'rejected': list(self._current_session_events.get('rejected', [])),
                'analyses': list(self._current_session_events.get('analyses', [])),
                'post_mortems': list(self._current_session_events.get('post_mortems', [])),
            }
            all_sessions_to_display = recorded_sessions + [active_session_view]

        if not all_sessions_to_display:
            lines.append("*Aucune session active enregistrée.*")
        else:
            for s_idx, sess in enumerate(all_sessions_to_display, 1):
                s_name = sess.get('name', f'Session #{s_idx}')
                lines.append(f"### Session : {s_name} (Clôture / Statut : {sess.get('closed_at', '—')})")
                lines.append(f"- **PnL Session** : `{sess.get('pnl', 0.0):+.2f} €` | **Trades réalisés** : `{sess.get('trades_count', 0)}`")
                lines.append("")

                # A. Analyses préalables ("Pourquoi et Comment")
                analyses = sess.get('analyses', [])
                if analyses:
                    lines.append("#### 🔍 Analyses Préalables & Choix Stratégiques (Le Pourquoi)")
                    for a in analyses[-6:]:
                        lines.append(f"- `[{a.get('time')}]` **{a.get('symbol')}** (Régime : *{a.get('regime')}*, Score: *{a.get('score', 0):.1f}*, R:R: *{a.get('rr', 0):.2f}*)")
                        lines.append(f"  - **Décision & Rationale** : {a.get('rationale')}")
                    lines.append("")

                # B. Ordres Exécutés
                trades = sess.get('trades', [])
                if trades:
                    lines.append("#### 🚀 Ordres Exécutés")
                    lines.append("| Heure | Symbole | Sens | Lots | Entrée | SL | TP | R:R | Rationale |")
                    lines.append("|---|---|---|---|---|---|---|---|---|")
                    for t in trades:
                        side = t.get('side', '').upper()
                        sym = t.get('symbol', '')
                        lots = t.get('lots', t.get('position_size', t.get('size', 0.0)))
                        entry = t.get('entry_price', 0.0)
                        sl = t.get('stop_loss', t.get('sl', 0.0))
                        tp = t.get('take_profit', t.get('tp', 0.0))
                        strat = t.get('strategy_name', t.get('strategy', '—'))
                        rr = t.get('rr_ratio', 0.0)
                        if rr == 0.0 and abs(entry - sl) > 0:
                            rr = abs(tp - entry) / abs(entry - sl)
                        rat = t.get('decision_rationale', t.get('comment', ''))
                        lines.append(f"| {t.get('time', '—')} | **{sym}** | `{side}` | {lots} | {entry:.5f} | {sl:.5f} | {tp:.5f} | {rr:.2f} | *{strat}* : {rat[:60]}... |")
                    lines.append("")

                # C. Diagnostics Post-Mortem & Analyses de Pertes (Pauses 10 min)
                post_mortems = sess.get('post_mortems', [])
                if post_mortems:
                    lines.append("#### 🔬 Diagnostics Post-Mortem & Analyses de Pertes (Pauses 10 min)")
                    for pm in post_mortems:
                        sym = pm.get('symbol', '')
                        losses = pm.get('consecutive_losses', 2)
                        cause = pm.get('cause', '')
                        adapt = pm.get('adapted_parameters', {})
                        t = pm.get('time', '')
                        lines.append(f"- `[{t}]` **{sym}** : ⚠️ **{losses} pertes consécutives** détectées.")
                        lines.append(f"  - **Diagnostic de cause** : {cause}")
                        lines.append(f"  - **Action conservatoire** : Suspension immédiate de 10 min sur {sym} pour ré-analyse.")
                        if adapt:
                            adapt_str = ", ".join(f"`{k}`: {v}" for k, v in adapt.items())
                            lines.append(f"  - **Adaptations stratégiques post-pause** : {adapt_str}")
                    lines.append("")

                # D. Opportunités Filtrées / Rejetées
                rejected = sess.get('rejected', [])
                if rejected:
                    lines.append("#### 🛡️ Opportunités Filtrées / Rejetées (Préservation du Capital)")
                    for r in rejected[-5:]:
                        lines.append(f"- `[{r.get('time')}]` **{r.get('symbol')}** rejeté : {r.get('reason')}")
                    lines.append("")

        # ── 4. AUTO-APPRENTISSAGE & ADAPTATIONS ───────────────────────────────
        lines.append("## 🧠 4. Auto-Apprentissage & Adaptations Autonomes")
        if self.performance_learner:
            try:
                params = self.performance_learner.get_current_params()
                lines.append(f"- **Score Minimum Requis (`score_min`)** : `{params.get('score_min', 6)}`")
                lines.append(f"- **Risque par Position (`risk_pct`)** : `{params.get('risk_pct', 1.0)}%`")
                lines.append(f"- **Positions Max Ouvertes** : `{params.get('max_positions', 3)}`")
                lines.append(f"- **Multiplicateur Stop-Loss ATR** : `{params.get('sl_atr_mult', 1.5)}×`")
                lines.append(f"- **Multiplicateur Take-Profit ATR** : `{params.get('tp_atr_mult', 3.0)}×`")

                # Pauses actives 10 min
                if hasattr(self.performance_learner, 'get_active_pauses'):
                    active_pauses = self.performance_learner.get_active_pauses()
                    if active_pauses:
                        lines.append("")
                        lines.append("### ⏳ Pauses 10 min Actuellement en Cours")
                        for sym, p_info in active_pauses.items():
                            lines.append(f"- **{sym}** : pause de 10 min en cours suite à {p_info.get('consecutive_losses')} pertes consécutives (reste {p_info.get('remaining_minutes')} min, fin programmée à {p_info.get('blocked_at')}).")

                # Paramètres adaptés par actif
                adapted_syms = getattr(self.performance_learner, '_symbol_adapted_params', {})
                if adapted_syms:
                    lines.append("")
                    lines.append("### 🎯 Paramètres Stratégiques Adaptés par Actif")
                    for sym, ad_vals in adapted_syms.items():
                        ad_str = ", ".join(f"`{k}`: {v}" for k, v in ad_vals.items() if k != 'adapted_at')
                        lines.append(f"- **{sym}** : {ad_str}")

                blocked = list(getattr(self.performance_learner, '_blocked_symbols', set()))
                if blocked:
                    lines.append(f"- **Symboles Bloqués Session** : `{', '.join(blocked)}`.")

                decisions = getattr(self.performance_learner, '_decisions_log', [])
                if decisions:
                    lines.append("")
                    lines.append("### Décisions Récentes du PerformanceLearner")
                    for dec in decisions[-5:]:
                        lines.append(f"- `[{dec.get('time', '')}]` **{dec.get('type', 'Ajustement')}** : {dec.get('reason', '')}")
            except Exception as e:
                lines.append(f"*Données d'apprentissage indisponibles : {e}*")
        else:
            lines.append("*PerformanceLearner non disponible*")
        lines.append("")

        # ── 5. INTELLIGENCE MACROÉCONOMIQUE (KNOWLEDGE FEEDER) ────────────────
        lines.append("## 🌐 5. Contexte Macro & Sentiment Marché")
        if self.knowledge_feeder:
            try:
                sentiment = self.knowledge_feeder.get_current_sentiment()
                lines.append(f"- **Fear & Greed Index** : `{sentiment.get('fear_greed_index', '—')}`")
                lines.append(f"- **Sentiment Macro Global** : `{sentiment.get('overall_sentiment', 'neutre')}`")
                lines.append(f"- **Ressources Ingestionnées** : `{getattr(self.knowledge_feeder, '_items_today', 0)}`")
            except Exception as e:
                lines.append(f"*Données sentiment indisponibles : {e}*")
        else:
            lines.append("*KnowledgeFeeder non disponible*")
        lines.append("")

        # ── 6. ORIENTATION POUR LA PROCHAINE SESSION ─────────────────────────
        lines.append("## 🔄 6. Stratégie & Réglages pour la Prochaine Session")
        from superbot.broker.symbol_specs import is_weekend_market
        is_weekend = is_weekend_market(now_utc)
        if is_weekend:
            lines.append("- **Mode Actif** : `WEEKEND_CRYPTO` 🪙")
            lines.append("  - Marchés traditionnels fermés. Scan et exécution exclusifs sur les paires crypto MT5 (`BTCUSD`, `ETHUSD`, `BNBUSD`, `XRPUSD`, `SOLUSD`).")
        else:
            lines.append("- **Mode Actif** : `SEMAINE_INSTITUTIONNELLE` 🏛️")
            lines.append("  - Surveillance focalisée sur les Matières Premières (`XAUUSD`, `XAGUSD`, `XTIUSD`, `XBRUSD`, `XNGUSD`) et les 5 grandes devises (`EURUSD`, `GBPUSD`, `EURGBP`, `EURJPY`, `USDJPY`).")

        if achieved >= target:
            lines.append("- **Comportement Risque** : Mode `CONSERVATION` (Objectif journalier atteint, protection des gains acquis).")
        elif achieved < -50.0:
            lines.append("- **Comportement Risque** : Mode `DÉFENSIF` (Risque réduit de 50% pour préserver le capital).")
        else:
            lines.append("- **Comportement Risque** : Mode `STANDARD` (Exploitation des signaux à haute probabilité R:R >= 2.0).")

        lines.append("")
        lines.append("---")
        lines.append("*Document auto-généré par NexQuant V3 — Journal d'analyse et de décision.*")

        report_md = "\n".join(lines)

        # Sauvegarder sur disque
        try:
            fname = os.path.join(self.REPORTS_DIR, f"report_{date_str}.md")
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(report_md)
            log.info(f"📄 Rapport journalier mis à jour avec succès : {fname}")
        except Exception as e:
            log.warning(f"Erreur sauvegarde rapport journalier : {e}")

        # Sauvegarder en DB
        if self.db:
            try:
                self.db.insert_knowledge_item({
                    'url': f'report://{date_str}',
                    'source': 'ReportGenerator',
                    'title': f'Rapport journalier {date_str}',
                    'content': report_md[:4000],
                    'category': 'daily_report',
                })
            except Exception as e:
                log.debug(f"DB insert report error: {e}")

        return report_md

    def start_daily_scheduler(self):
        """
        Lance le scheduler pour générer le rapport automatiquement
        à 22:30 UTC chaque jour.
        """
        self._running = True
        self._schedule_next()
        log.info("ReportGenerator scheduler démarré (rapport quotidien à 22:30 UTC)")

    def _schedule_next(self):
        """Planifie la prochaine génération de rapport."""
        if not self._running:
            return

        now_utc = datetime.now(timezone.utc)
        target_hour, target_min = 22, 30

        next_report = now_utc.replace(hour=target_hour, minute=target_min, second=0, microsecond=0)
        if next_report <= now_utc:
            # Programmer pour demain
            from datetime import timedelta
            next_report = next_report + timedelta(days=1)

        delay_seconds = (next_report - now_utc).total_seconds()
        log.info(f"Prochain rapport dans {delay_seconds/3600:.1f}h (à {next_report.strftime('%Y-%m-%d %H:%M UTC')})")

        self._timer = threading.Timer(delay_seconds, self._run_and_reschedule)
        self._timer.daemon = True
        self._timer.start()

    def _run_and_reschedule(self):
        """Génère le rapport et reprogramme."""
        try:
            log.info("Génération du rapport journalier automatique...")
            report = self.generate_daily_report()
            log.info(f"Rapport généré ({len(report)} caractères)")
        except Exception as e:
            log.error(f"Erreur génération rapport automatique: {e}")
        finally:
            if self._running:
                self._schedule_next()

    def stop(self):
        """Arrête le scheduler."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        log.info("ReportGenerator arrêté")
