# Démarre le contrôleur Telegram en arrière-plan (sans fenêtre). Une seule instance possible.
$Root = Split-Path -Parent $PSScriptRoot
$Pythonw = Join-Path (Split-Path (Get-Command python -ErrorAction Stop).Source) 'pythonw.exe'
Start-Process -FilePath $Pythonw -ArgumentList '-m', 'superbot.telegram_controller' -WorkingDirectory $Root
Start-Sleep -Seconds 3
$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*superbot.telegram_controller*' }
if ($p) { Write-Host "Contrôleur Telegram démarré (PID $($p.ProcessId)). Log : superbot\logs\telegram_controller.log" }
else { Write-Host "Échec : vérifiez TELEGRAM_BOT_TOKEN dans le .env (lancer 'python -m superbot.telegram_controller' pour voir l'erreur)."; exit 1 }
