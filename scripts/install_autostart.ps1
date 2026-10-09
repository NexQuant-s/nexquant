# Installe le démarrage automatique de NexQuant à l'ouverture de session Windows (tâche planifiée,
# relance automatique en cas d'arrêt) et crée deux raccourcis sur le Bureau.
# Désinstaller : Unregister-ScheduledTask -TaskName "NexQuant SuperBot" -Confirm:$false
$Scripts = $PSScriptRoot
$Start = Join-Path $Scripts 'start_bot.ps1'
$Stop  = Join-Path $Scripts 'stop_bot.ps1'
$Pwsh  = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $Pwsh) { $Pwsh = (Get-Command powershell).Source }

# MT5 a besoin de la session utilisateur : déclenchement à l'ouverture de session (pas au démarrage machine)
$action   = New-ScheduledTaskAction -Execute $Pwsh -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Start`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Relais toutes les 5 min : relance le bot s'il est tombé (start_bot.ps1 est idempotent, le verrou empêche tout doublon)
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 5) `
            -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'NexQuant SuperBot' -Action $action -Trigger @($trigger, $watchdog) -Settings $settings -Force | Out-Null
Write-Host "Tâche planifiée 'NexQuant SuperBot' installée (lancement à l'ouverture de session)."

# Contrôleur Telegram (pilotage depuis le téléphone) : processus séparé, sans fenêtre, toujours actif
$Root = Split-Path -Parent $Scripts
$Pythonw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
$envFile = Join-Path $Root '.env'
$hasToken = (Test-Path $envFile) -and ((Get-Content $envFile) -match '^TELEGRAM_BOT_TOKEN=\S+')
if ($hasToken) {
$tgAction = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m superbot.telegram_controller' -WorkingDirectory $Root
Register-ScheduledTask -TaskName 'NexQuant Telegram' -Action $tgAction -Trigger @($trigger, $watchdog) -Settings $settings -Force | Out-Null
Write-Host "Tâche planifiée 'NexQuant Telegram' installée."
} else { Write-Host "Contrôleur Telegram non installé : renseignez TELEGRAM_BOT_TOKEN dans le .env puis relancez ce script." }

# Gestionnaire swing D1 (indices + ETH) : un passage par heure, idempotent, indépendant du bot H1
$swAction   = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m superbot.swing_runner' -WorkingDirectory $Root
$swTrigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$swSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
              -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName 'NexQuant Swing' -Action $swAction -Trigger $swTrigger -Settings $swSettings -Force | Out-Null
Write-Host "Tâche planifiée 'NexQuant Swing' installée (un passage par heure ; actif si SWING_ENABLED=true dans le .env)."

$Desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
foreach ($item in @(@('Démarrer NexQuant', $Start), @('Arrêter NexQuant', $Stop))) {
    $lnk = $shell.CreateShortcut((Join-Path $Desktop "$($item[0]).lnk"))
    $lnk.TargetPath = $Pwsh
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$($item[1])`""
    $lnk.WorkingDirectory = $Scripts
    $lnk.Save()
}
Write-Host "Raccourcis créés sur le Bureau : 'Démarrer NexQuant' et 'Arrêter NexQuant'."
