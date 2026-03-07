#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Hot-fix the live AWS server to resolve the 3 crash issues:
    1. PermissionError on data/ directories
    2. /health returns 302 (auth redirect) instead of 200
    3. Log files not writable by businessapp
.PARAMETER ServerIP
    EC2 public IP address
.EXAMPLE
    .\hotfix_server.ps1 -ServerIP 16.28.104.60
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,
    [string]$SSHKey = "$HOME\.ssh\id_rsa"
)

function Write-OK   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Fail { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }
function Write-Step { param($m) Write-Host "`n=> $m" -ForegroundColor Cyan }

$sshTarget = "ubuntu@$ServerIP"
$sshOpts   = @('-o','StrictHostKeyChecking=no','-o','ConnectTimeout=10','-i',$SSHKey)

Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "  Ethiopian Business — Live Server Hotfix" -ForegroundColor Yellow
Write-Host "  Target: $ServerIP" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Yellow

# ── Step 1: Test SSH ──────────────────────────────────────────────
Write-Step "Testing SSH connectivity..."
$test = ssh @sshOpts $sshTarget "echo OK" 2>&1
if ($test -notmatch "OK") {
    Write-Fail "Cannot SSH to $ServerIP"
    exit 1
}
Write-OK "SSH connected"

# ── Step 2: Fix log file permissions ──────────────────────────────
Write-Step "Fixing log file permissions..."
ssh @sshOpts $sshTarget @"
sudo touch /var/log/ethiopian-business.log /var/log/ethiopian-business-error.log /var/log/ethiopian-business-access.log
sudo chown businessapp:businessapp /var/log/ethiopian-business.log /var/log/ethiopian-business-error.log /var/log/ethiopian-business-access.log
echo LOGFIX_OK
"@ 2>&1 | ForEach-Object { if ($_ -match "LOGFIX_OK") { Write-OK "Log files created and owned by businessapp" } }

# ── Step 3: Create all data directories ───────────────────────────
Write-Step "Creating data directories with correct ownership..."
ssh @sshOpts $sshTarget @"
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/platform
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/auth
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/bids
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/bids/documents
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/backups
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/siem
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/versions
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/exports
sudo -u businessapp mkdir -p /opt/ethiopian-business/data
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/sample_files
sudo chown -R businessapp:businessapp /opt/ethiopian-business/web/data
sudo chown -R businessapp:businessapp /opt/ethiopian-business/data
echo DIRFIX_OK
"@ 2>&1 | ForEach-Object { if ($_ -match "DIRFIX_OK") { Write-OK "All data directories created" } }

# ── Step 4: Patch run_production.py (sys.path + /health route) ────
Write-Step "Patching run_production.py..."
ssh @sshOpts $sshTarget @"
sudo tee /opt/ethiopian-business/run_production.py << 'PYEOF'
#!/usr/bin/env python3
"""Production entry point for gunicorn."""
import os
import sys

from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path, override=True)

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'web'))

from web.app import app

@app.route('/health')
def health_check():
    return {'status': 'healthy', 'service': 'Ethiopian Business Management System'}, 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
PYEOF
sudo chown businessapp:businessapp /opt/ethiopian-business/run_production.py
echo RPFIX_OK
"@ 2>&1 | ForEach-Object { if ($_ -match "RPFIX_OK") { Write-OK "run_production.py patched" } }

# ── Step 5: Patch app.py — whitelist /health in auth gate ─────────
Write-Step "Patching app.py to whitelist /health..."
ssh @sshOpts $sshTarget @"
cd /opt/ethiopian-business

# Add 'health_check' to PUBLIC_ENDPOINTS if missing
if ! grep -q "'health_check'" web/app.py; then
    sudo sed -i "s/'sales.contact',.*# contact-form handler/'sales.contact',                  # contact-form handler\n    'health_check',                   # ALB \/ monitoring health endpoint/" web/app.py
    echo ENDPOINT_ADDED
else
    echo ENDPOINT_EXISTS
fi

# Add '/health' to PUBLIC_PREFIXES if missing
if ! grep -q "'/health'" web/app.py; then
    sudo sed -i "s|'/static/', '/provider/', '/sales/')|'/static/', '/provider/', '/sales/', '/health')|" web/app.py
    echo PREFIX_ADDED
else
    echo PREFIX_EXISTS
fi

# Add direct /health path check in require_login_globally if missing
if ! grep -q "request.path == '/health'" web/app.py; then
    sudo sed -i "s|if request.path.startswith('/static/') or request.path == '/favicon.ico':|if request.path == '/health' or request.path.startswith('/static/') or request.path == '/favicon.ico':|" web/app.py
    echo PATHCHECK_ADDED
else
    echo PATHCHECK_EXISTS
fi

sudo chown businessapp:businessapp web/app.py
echo APPFIX_OK
"@ 2>&1 | ForEach-Object {
    if ($_ -match "ENDPOINT_ADDED") { Write-OK "Added 'health_check' to PUBLIC_ENDPOINTS" }
    if ($_ -match "PREFIX_ADDED")   { Write-OK "Added '/health' to PUBLIC_PREFIXES" }
    if ($_ -match "PATHCHECK_ADDED"){ Write-OK "Added /health path check to auth gate" }
    if ($_ -match "_EXISTS")        { Write-OK "$($_ -replace '_',' ')" }
    if ($_ -match "APPFIX_OK")      { Write-OK "app.py patched" }
}

# ── Step 6: Kill any stuck processes and restart ──────────────────
Write-Step "Restarting services..."
ssh @sshOpts $sshTarget @"
# Stop any conflicting systemd service
sudo systemctl stop ethiopian-business 2>/dev/null
sudo systemctl disable ethiopian-business 2>/dev/null

# Kill anything stuck on port 5000
sudo fuser -k 5000/tcp 2>/dev/null
sleep 2

# Reload and restart supervisor
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart ethiopian-business

# Restart nginx
sudo systemctl restart nginx

sleep 5

# Check status
echo SUPERVISOR_STATUS=\$(sudo supervisorctl status ethiopian-business)
echo PORT_CHECK=\$(sudo ss -tlnp | grep ':5000 ')
echo HEALTH_CHECK=\$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:5000/health)
"@ 2>&1 | ForEach-Object {
    if ($_ -match "SUPERVISOR_STATUS=(.+)") {
        $status = $Matches[1]
        if ($status -match "RUNNING") { Write-OK "Supervisor: $status" }
        else { Write-Fail "Supervisor: $status" }
    }
    if ($_ -match "PORT_CHECK=(.+)") {
        Write-OK "Port 5000: $($Matches[1])"
    }
    if ($_ -match "HEALTH_CHECK=(.+)") {
        $code = $Matches[1]
        if ($code -eq "200") { Write-OK "Health check: HTTP $code" }
        else { Write-Fail "Health check: HTTP $code" }
    }
}

# ── Step 7: Verify from outside ──────────────────────────────────
Write-Step "Verifying from external..."
Start-Sleep -Seconds 3
try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://$ServerIP/health" -TimeoutSec 10 -ErrorAction Stop
    Write-OK "External health check: HTTP $($resp.StatusCode)"
    Write-Host "`n  $($resp.Content)" -ForegroundColor DarkGray
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Write-Fail "External health check: HTTP $code"
    if ($code -eq 302) { Write-Fail "Still redirecting to login! Auth gate patch may have failed." }
    if ($code -eq 502) { Write-Fail "502 Bad Gateway — app still not running on port 5000" }
}

Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "  Hotfix complete!" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Yellow
Write-Host "  If the app is still failing, check:" -ForegroundColor DarkGray
Write-Host "    ssh $sshTarget 'sudo tail -50 /var/log/ethiopian-business.log'" -ForegroundColor DarkGray
Write-Host "    ssh $sshTarget 'sudo tail -50 /var/log/ethiopian-business-error.log'" -ForegroundColor DarkGray
