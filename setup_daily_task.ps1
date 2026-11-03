# Creates the Windows scheduled task that runs daily_update.bat every morning at 07:25.
# If the PC is off or asleep at 07:25, it runs as soon as it can afterwards. Run once:
#   powershell -ExecutionPolicy Bypass -File setup_daily_task.ps1
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$action = New-ScheduledTaskAction -Execute (Join-Path $dir "daily_update.bat") -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Daily -At 7:25am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Hours 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "Football Safe Picks daily update" `
  -Description "Runs src/update.py and pushes the new picks to GitHub" `
  -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
$info = Get-ScheduledTask -TaskName "Football Safe Picks daily update" | Get-ScheduledTaskInfo
Write-Host "Task created. Next run: $($info.NextRunTime)"
