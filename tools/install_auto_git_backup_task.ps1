[CmdletBinding()]
param(
    [string]$RepoPath,
    [ValidateRange(1, 1440)][int]$IntervalMinutes = 5,
    [string]$TaskName = "VideoProductionAutomation-GitBackup"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent $PSScriptRoot
}

$backupScript = Join-Path $RepoPath "tools\auto_git_backup.ps1"
if (-not (Test-Path -LiteralPath $backupScript -PathType Leaf)) {
    throw "Backup script not found: $backupScript"
}

$windowsPowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$actionArguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$backupScript`" -RepoPath `"$RepoPath`""
$action = New-ScheduledTaskAction -Execute $windowsPowerShell -Argument $actionArguments

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1)
$trigger.Repetition.Interval = "PT${IntervalMinutes}M"
$trigger.Repetition.Duration = "P3650D"
$trigger.Repetition.StopAtDurationEnd = $false

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Back up system changes to origin/main; projects/ is always excluded." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$TaskName' every $IntervalMinutes minute(s)."
