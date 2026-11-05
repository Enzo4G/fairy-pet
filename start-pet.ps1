# Start the Fairy pet (dsh build).
# - one instance only (the program owns the mutex)
# - does not wait for anything: it finds a running dsh on its own

$ErrorActionPreference = "SilentlyContinue"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path (Split-Path -Parent $here) ".petenv\Scripts\pythonw.exe"
$script = Join-Path $here "pet.py"
$log = Join-Path $here "startup.log"

function Write-Note($text) {
    $stamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -LiteralPath $log -Value "$stamp  $text" -Encoding utf8
}

$running = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*pet.py*" }
if ($running) {
    Write-Note "already running (pid $($running.ProcessId -join ','))"
    exit 0
}

if (-not (Test-Path $python)) {
    Write-Note "pythonw not found: $python"
    exit 1
}

Start-Process -FilePath $python -ArgumentList @($script) -WorkingDirectory $here -WindowStyle Hidden
Write-Note "pet launched"
