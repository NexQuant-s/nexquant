# Arrête le SuperBot NexQuant. Les positions ouvertes restent chez le broker avec leurs SL/TP.
$p = Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*superbot.main*' }
if (-not $p) { Write-Host "NexQuant n'est pas lancé."; exit 0 }
foreach ($x in $p) { Stop-Process -Id $x.ProcessId -Confirm:$false; Write-Host "NexQuant arrêté (PID $($x.ProcessId))." }
