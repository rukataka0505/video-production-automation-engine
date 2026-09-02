[CmdletBinding()]
param(
    [string]$RepoPath
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoPath)) {
    $RepoPath = Split-Path -Parent $PSScriptRoot
}

$logDirectory = Join-Path $env:LOCALAPPDATA "VideoProductionAutomationBackup"
$logPath = Join-Path $logDirectory "backup.log"
$lockPath = Join-Path $logDirectory "backup.lock"

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

function Write-BackupLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Invoke-Git {
    $output = & git -C $RepoPath @args 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($args -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return $output
}

$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch [System.IO.IOException] {
    Write-BackupLog "Skipped because another backup is already running."
    exit 0
}

try {
    if (-not (Test-Path -LiteralPath (Join-Path $RepoPath ".git"))) {
        throw "Not a Git repository: $RepoPath"
    }

    $branch = (Invoke-Git rev-parse --abbrev-ref HEAD | Select-Object -First 1).Trim()
    if ($branch -ne "main") {
        throw "Automatic backup only runs on main; current branch is $branch."
    }

    $trackedProjects = @(Invoke-Git ls-files -- projects)
    if ($trackedProjects.Count -gt 0) {
        throw "projects/ is tracked by Git. Remove it from the index before automatic backup."
    }

    Invoke-Git add -A -- . | Out-Null

    $blockedNames = @(
        Invoke-Git diff --cached --name-only --diff-filter=ACMR |
            Where-Object {
                $_ -match '(^|/)(\.env($|\.)|client_secret|credentials\.json$|.*oauth.*token.*\.json$|.*\.(pem|pfx|key)$)'
            }
    )
    if ($blockedNames.Count -gt 0) {
        Invoke-Git reset -- @blockedNames | Out-Null
        throw "Potential secret files were left uncommitted: $($blockedNames -join ', ')"
    }

    & git -C $RepoPath diff --cached --quiet
    if ($LASTEXITCODE -eq 1) {
        $message = "Automatic system backup $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Invoke-Git commit -m $message | Out-Null
        Write-BackupLog "Committed system changes."
    } elseif ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect staged changes."
    }

    Invoke-Git push origin main | Out-Null
    Write-BackupLog "Backup is up to date on origin/main."
} catch {
    Write-BackupLog "ERROR: $($_.Exception.Message)"
    exit 1
} finally {
    if ($null -ne $lockStream) {
        $lockStream.Dispose()
    }
}
