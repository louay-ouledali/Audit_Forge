<#
.SYNOPSIS
    Start AuditForge — one command for everything.

.DESCRIPTION
    Launches the discovery agent on the host (for real MAC/device detection)
    and docker-compose for the backend + frontend.

    Usage:  .\start.ps1
    Stop:   .\start.ps1 -Stop
#>

param(
    [switch]$Stop
)

$ErrorActionPreference = "Continue"
$AgentPort = 37120
$AgentScript = Join-Path $PSScriptRoot "discovery_agent.py"

function Stop-All {
    Write-Host "`n[AuditForge] Stopping services..." -ForegroundColor Yellow

    # Stop docker-compose
    docker compose down 2>$null

    # Stop discovery agent
    $agentProcs = Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%discovery_agent.py%'" -ErrorAction SilentlyContinue
    foreach ($p in $agentProcs) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped discovery agent (PID $($p.ProcessId))" -ForegroundColor Gray
    }

    Write-Host "[AuditForge] All services stopped." -ForegroundColor Green
}

if ($Stop) {
    Stop-All
    return
}

Push-Location $PSScriptRoot

Write-Host ""
Write-Host "  ╔═══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║       AuditForge — Starting Up        ║" -ForegroundColor Cyan
Write-Host "  ╚═══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. Start discovery agent on the host ──
$agentRunning = $false
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:$AgentPort/health" -TimeoutSec 2 -ErrorAction Stop
    if ($resp.status -eq "ok") { $agentRunning = $true }
} catch {}

if ($agentRunning) {
    Write-Host "  [OK] Discovery agent already running on port $AgentPort" -ForegroundColor Green
} else {
    Write-Host "  [..] Starting discovery agent on port $AgentPort..." -ForegroundColor Yellow
    $job = Start-Process -FilePath "python" -ArgumentList $AgentScript -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2

    # Verify it started
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:$AgentPort/health" -TimeoutSec 3 -ErrorAction Stop
        if ($resp.status -eq "ok") {
            Write-Host "  [OK] Discovery agent running (PID $($job.Id))" -ForegroundColor Green
        }
    } catch {
        Write-Host "  [!!] Discovery agent may have failed to start. Check Python 3.10+" -ForegroundColor Red
    }
}

# ── 2. Start Docker services ──
Write-Host "  [..] Starting Docker services (backend + frontend)..." -ForegroundColor Yellow
docker compose up -d --build 2>&1 | ForEach-Object {
    if ($_ -match "Started|Created|Running|up") {
        Write-Host "  $_" -ForegroundColor Gray
    }
}

Start-Sleep -Seconds 3

# ── 3. Verify everything ──
Write-Host ""
Write-Host "  ── Service Status ──" -ForegroundColor Cyan

# Check backend
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/api/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  Backend:    http://localhost:8000    [OK]" -ForegroundColor Green
} catch {
    Write-Host "  Backend:    http://localhost:8000    [STARTING...]" -ForegroundColor Yellow
}

# Check frontend
try {
    $null = Invoke-WebRequest -Uri "http://localhost:5173" -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    Write-Host "  Frontend:   http://localhost:5173    [OK]" -ForegroundColor Green
} catch {
    Write-Host "  Frontend:   http://localhost:5173    [STARTING...]" -ForegroundColor Yellow
}

# Check agent
try {
    $agent = Invoke-RestMethod -Uri "http://localhost:$AgentPort/health" -TimeoutSec 2 -ErrorAction Stop
    Write-Host "  Agent:      http://localhost:$AgentPort  [OK]" -ForegroundColor Green
} catch {
    Write-Host "  Agent:      http://localhost:$AgentPort  [DOWN]" -ForegroundColor Red
}

Write-Host ""
Write-Host "  Open http://localhost:5173 in your browser" -ForegroundColor White
Write-Host "  Stop with: .\start.ps1 -Stop" -ForegroundColor Gray
Write-Host ""

Pop-Location
