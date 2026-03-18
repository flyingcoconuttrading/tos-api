# start.ps1 — TOS-API startup script (PowerShell)
# Run from PowerShell: .\start.ps1
# If blocked by execution policy: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "SilentlyContinue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " TOS-API | Starting up..." -ForegroundColor Cyan
Write-Host "============================================================"
Write-Host ""

# ── 1. Kill stray python and node processes ───────────────────────────────
Write-Host "[1/5] Stopping stray python.exe and node.exe..." -ForegroundColor Yellow
Stop-Process -Name "python" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "node"   -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500
Write-Host "      Done." -ForegroundColor Green
Write-Host ""

# ── 2. Kill anything holding ports 3000 and 8002 ─────────────────────────
Write-Host "[2/5] Freeing ports 3000 and 8002..." -ForegroundColor Yellow

foreach ($port in @(3000, 8002)) {
    $connections = netstat -aon | Select-String ":$port\s"
    foreach ($line in $connections) {
        $parts = $line.ToString().Trim() -split '\s+'
        $pid   = $parts[-1]
        if ($pid -match '^\d+$' -and $pid -ne '0') {
            Write-Host "      Killing PID $pid on port $port"
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "      Done." -ForegroundColor Green
Write-Host ""

# ── 3. Start Python API server ────────────────────────────────────────────
Write-Host "[3/5] Starting Python API on port 8002..." -ForegroundColor Yellow
Start-Process "cmd" -ArgumentList '/k', `
    'cd /d C:\Users\randy\tos-api && venv313\Scripts\activate && uvicorn main:app --reload --port 8002' `
    -WindowStyle Normal
Write-Host "      Window launched." -ForegroundColor Green
Write-Host ""

# ── 4. Wait for API to initialize ─────────────────────────────────────────
Write-Host "[4/5] Waiting 3s for API to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
Write-Host "      Ready." -ForegroundColor Green
Write-Host ""

# ── 5. Start React dev server ─────────────────────────────────────────────
Write-Host "[5/5] Starting React dev server on port 3000..." -ForegroundColor Yellow
Start-Process "cmd" -ArgumentList '/k', `
    'cd /d C:\Users\randy\hg-frontend && npm start' `
    -WindowStyle Normal
Write-Host "      Window launched." -ForegroundColor Green
Write-Host ""

# ── 6. Open browser ───────────────────────────────────────────────────────
Write-Host "Waiting 5s then opening http://localhost:3000 ..." -ForegroundColor Yellow
Start-Sleep -Seconds 5
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " All services started." -ForegroundColor Cyan
Write-Host " API:      http://localhost:8002/docs" -ForegroundColor White
Write-Host " App:      http://localhost:3000" -ForegroundColor White
Write-Host " Settings: http://localhost:8002/settings-ui" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor Cyan
