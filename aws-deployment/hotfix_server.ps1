<#
.SYNOPSIS
    Cleaned Hot-fix for Ethiopian Business Server
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,
    [string]$SSHKey = "$HOME\.ssh\id_rsa"
)

function Write-OK   { param($m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Fail { param($m) Write-Host "  [FAIL]  $m" -ForegroundColor Red }
function Write-Step { param($m) Write-Host "`n=> $m" -ForegroundColor Cyan }

$sshTarget = "ubuntu@$ServerIP"
$sshOpts   = @('-o','StrictHostKeyChecking=no','-o','ConnectTimeout=10','-i',$SSHKey)

Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "  Ethiopian Business — Fixed Hotfix" -ForegroundColor Yellow
Write-Host "  Target: $ServerIP" -ForegroundColor Yellow
Write-Host "========================================`n"

# -- Step 1: Test SSH --
Write-Step "Testing SSH connectivity..."
$test = & ssh @sshOpts $sshTarget "echo OK" 2>&1
if ($test -notmatch "OK") {
    Write-Fail "Cannot SSH to $ServerIP. Check security groups/key."
    exit 1
}
Write-OK "SSH connected"

# -- Step 2: Fix Log Permissions --
Write-Step "Fixing log file permissions..."
$logCmd = "sudo touch /var/log/ethiopian-business.log /var/log/ethiopian-business-error.log; " +
          "sudo chown businessapp:businessapp /var/log/ethiopian-business*; echo LOGFIX_OK"
& ssh @sshOpts $sshTarget $logCmd | ForEach-Object { if ($_ -match "LOGFIX_OK") { Write-OK "Logs fixed" } }

# -- Step 3: Patch run_production.py --
# Using a single-quoted string to prevent local variable expansion
Write-Step "Patching run_production.py naming conflict..."
$pyPatch = @'
sudo tee /opt/ethiopian-business/run_production.py << 'PYEOF'
import os
import sys
from dotenv import load_dotenv
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'web'))
from web.app import app
@app.route('/health')
def production_health_check():
    return {'status': 'healthy'}, 200
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
PYEOF
sudo chown businessapp:businessapp /opt/ethiopian-business/run_production.py
echo RPFIX_OK
'@
& ssh @sshOpts $sshTarget $pyPatch | ForEach-Object { if ($_ -match "RPFIX_OK") { Write-OK "run_production.py patched" } }

# -- Step 4: Restart & Verify --
Write-Step "Restarting Supervisor..."
$restartCmd = "sudo supervisorctl reread; sudo supervisorctl update; sudo supervisorctl restart ethiopian-business; sleep 2; sudo supervisorctl status ethiopian-business"
& ssh @sshOpts $sshTarget $restartCmd | ForEach-Object { 
    if ($_ -match "RUNNING") { Write-OK "App is RUNNING" }
    elseif ($_ -match "STOPPED|FATAL") { Write-Fail "App status: $_" }
}

# -- Step 5: External Health Check --
Write-Step "External verification..."
try {
    $resp = Invoke-WebRequest -Uri "http://$ServerIP/health" -UseBasicParsing -TimeoutSec 5
    Write-OK "External health check: HTTP $($resp.StatusCode)"
} catch {
    Write-Fail "Health check failed: $($_.Exception.Message)"
}