$ErrorActionPreference = 'Stop'

$voicevoxUrl = if ($env:VOICEVOX_URL) { $env:VOICEVOX_URL.TrimEnd('/') } else { 'http://127.0.0.1:50021' }
try {
    $version = Invoke-RestMethod -Uri "$voicevoxUrl/version" -TimeoutSec 2
    Write-Host "VOICEVOX ENGINE is already running: $version"
    exit 0
} catch {}

$engine = $null
if ($env:VOICEVOX_ENGINE -and (Test-Path -LiteralPath $env:VOICEVOX_ENGINE -PathType Leaf)) {
    $engine = Get-Item -LiteralPath $env:VOICEVOX_ENGINE
} else {
    $packageRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    $engine = Get-ChildItem -LiteralPath $packageRoot -Filter run.exe -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match 'HiroshibaKazuyuki\.VOICEVOX' } |
        Select-Object -First 1
}

if (-not $engine) {
    throw 'VOICEVOX ENGINE was not found. Install VOICEVOX using the winget command in README.md.'
}

Start-Process -FilePath $engine.FullName -ArgumentList @('--host', '127.0.0.1', '--port', '50021') -WorkingDirectory $engine.DirectoryName -WindowStyle Hidden | Out-Null

for ($attempt = 0; $attempt -lt 120; $attempt++) {
    try {
        $version = Invoke-RestMethod -Uri "$voicevoxUrl/version" -TimeoutSec 2
        Write-Host "VOICEVOX ENGINE ready: $version"
        exit 0
    } catch {
        Start-Sleep -Milliseconds 500
    }
}

throw 'VOICEVOX ENGINE did not become ready within 60 seconds.'
