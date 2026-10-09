# Arrête le SuperBot NexQuant (arrêt VOLONTAIRE : le relais automatique ne le relance pas tant que start_bot.ps1 n'est pas
# lancé sans -Watchdog, ou /demarrer sur Telegram). Les positions ouvertes restent chez le broker avec leurs SL/TP.
$Root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'superbot\logs') | Out-Null
Set-Content -Path (Join-Path $Root 'superbot\logs\user_stop.flag') -Value (Get-Date -Format o)
$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*superbot.main*' }
if (-not $p) { Write-Host "NexQuant n'est pas lancé (relance automatique suspendue)."; exit 0 }
foreach ($x in $p) { Stop-Process -Id $x.ProcessId -Confirm:$false; Write-Host "NexQuant arrêté (PID $($x.ProcessId)) ; relance automatique suspendue." }
