# Démarre le SuperBot NexQuant en arrière-plan (fenêtre réduite). Sans effet s'il tourne déjà :
# le bot refuse lui-même une seconde instance (verrou superbot_mt5.lock).
# -Watchdog : appel du relais automatique (tâche planifiée) -> respecte un arrêt volontaire (fichier user_stop.flag).
# Sans -Watchdog (raccourci Bureau, lancement manuel) : lève l'arrêt volontaire puis démarre.
param([switch]$Watchdog)
$Root = Split-Path -Parent $PSScriptRoot
$Flag = Join-Path $Root 'superbot\logs\user_stop.flag'
if ($Watchdog -and (Test-Path $Flag)) {
    Write-Host "Arrêt volontaire en cours (user_stop.flag) : pas de relance. /demarrer sur Telegram ou le raccourci Bureau pour relancer."
    exit 0
}
if (-not $Watchdog) { Remove-Item $Flag -ErrorAction SilentlyContinue }
$Python = (Get-Command python -ErrorAction Stop).Source

$running = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*superbot.main*' }
if ($running) { Write-Host "NexQuant tourne déjà (PID $($running.ProcessId -join ', '))."; exit 0 }

Start-Process -FilePath $Python -ArgumentList '-m', 'superbot.main' -WorkingDirectory $Root -WindowStyle Minimized
Start-Sleep -Seconds 5
$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*superbot.main*' }
if ($p) { Write-Host "NexQuant démarré (PID $($p.ProcessId)). Dashboard : http://127.0.0.1:5000" }
else { Write-Host "Échec du démarrage : voir superbot\logs\superbot_mt5.log"; exit 1 }
