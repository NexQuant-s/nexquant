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
$settings = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 5) `
            -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'NexQuant SuperBot' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Tâche planifiée 'NexQuant SuperBot' installée (lancement à l'ouverture de session)."

# Contrôleur Telegram (pilotage depuis le téléphone) : processus séparé, sans fenêtre, toujours actif
$Root = Split-Path -Parent $Scripts
$Pythonw = Join-Path (Split-Path (Get-Command python).Source) 'pythonw.exe'
$tgAction = New-ScheduledTaskAction -Execute $Pythonw -Argument '-m superbot.telegram_controller' -WorkingDirectory $Root
Register-ScheduledTask -TaskName 'NexQuant Telegram' -Action $tgAction -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Tâche planifiée 'NexQuant Telegram' installée (nécessite TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans le .env)."

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
