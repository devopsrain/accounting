#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Ethiopian Business Management System — AWS Diagnostics & Health Check
.DESCRIPTION
    Comprehensive diagnostic tool that collects all AWS logs, checks health
    of every layer (EC2, nginx, gunicorn, Flask app, RDS, ALB, S3), and
    suggests targeted fixes for any errors found.
.PARAMETER Action
    What to run: All, Health, Logs, Diagnose, Fix, Watch
.PARAMETER ServerIP
    EC2 public IP (auto-detected from terraform output if omitted)
.PARAMETER Region
    AWS region (default: af-south-1)
.EXAMPLE
    .\diagnose.ps1                    # Full diagnosis
    .\diagnose.ps1 -Action Health     # Quick health check only
    .\diagnose.ps1 -Action Logs       # Collect all logs
    .\diagnose.ps1 -Action Fix        # Attempt common auto-fixes
    .\diagnose.ps1 -Action Watch      # Continuous monitoring
#>

param(
    [ValidateSet('All','Health','Logs','Diagnose','Fix','Watch')]
    [string]$Action = 'All',

    [string]$ServerIP,
    [string]$Region = 'af-south-1',
    [string]$SSHKey = "$HOME\.ssh\id_rsa",
    [int]$WatchInterval = 30
)

# ── Colours ───────────────────────────────────────────────────────
function Write-OK      { param($m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "  [WARN]  $m" -ForegroundColor Yellow }
function Write-Fail    { param($m) Write-Host "  [FAIL]  $m" -ForegroundColor Red }
function Write-Info    { param($m) Write-Host "  [INFO]  $m" -ForegroundColor Cyan }
function Write-Section { param($m) Write-Host "`n═══ $m ═══" -ForegroundColor Magenta }

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir    = Join-Path $PSScriptRoot "diagnostic_logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$reportFile = Join-Path $logDir "diag_${timestamp}.txt"

# Tee output to report file
$findings = [System.Collections.Generic.List[string]]::new()
function Add-Finding {
    param([string]$Severity, [string]$Component, [string]$Message, [string]$Suggestion)
    $findings.Add("[$Severity] $Component — $Message | Fix: $Suggestion")
}

# ── Auto-detect server IP from Terraform ──────────────────────────
function Get-ServerIP {
    if ($ServerIP) { return $ServerIP }
    try {
        Push-Location $PSScriptRoot
        $ip = terraform output -raw web_server_ip 2>$null
        Pop-Location
        if ($ip) { return $ip }
    } catch {}
    Write-Fail "Cannot detect server IP. Use -ServerIP parameter."
    exit 1
}

# ── SSH helper ────────────────────────────────────────────────────
function Invoke-SSH {
    param([string]$Command, [int]$Timeout = 15)
    $result = ssh -o StrictHostKeyChecking=no -o ConnectTimeout=$Timeout -o BatchMode=yes -i $SSHKey "ubuntu@$script:ip" $Command 2>&1
    return ($result -join "`n")
}

# ── Terraform outputs ─────────────────────────────────────────────
function Get-TerraformOutputs {
    Write-Section "TERRAFORM OUTPUTS"
    try {
        Push-Location $PSScriptRoot
        $outputs = @{
            web_server_ip     = terraform output -raw web_server_ip 2>$null
            load_balancer_dns = terraform output -raw load_balancer_dns 2>$null
            database_endpoint = terraform output -raw database_endpoint 2>$null
            s3_bucket_name    = terraform output -raw s3_bucket_name 2>$null
        }
        Pop-Location
        foreach ($k in $outputs.Keys) {
            if ($outputs[$k]) { Write-OK "$k = $($outputs[$k])" }
            else { Write-Warn "$k = (empty)" }
        }
        return $outputs
    } catch {
        Write-Fail "Could not read terraform outputs: $_"
        return @{}
    }
}

# ═══════════════════════════════════════════════════════════════════
# HEALTH CHECKS
# ═══════════════════════════════════════════════════════════════════

function Test-SSHConnectivity {
    Write-Section "SSH CONNECTIVITY"
    try {
        $out = Invoke-SSH "echo OK" -Timeout 10
        if ($out -match "OK") { Write-OK "SSH connection successful" ; return $true }
        else { Write-Fail "SSH returned unexpected output: $out" ; return $false }
    } catch {
        Write-Fail "SSH connection failed: $_"
        Add-Finding "CRITICAL" "SSH" "Cannot connect to server" "Check security group allows port 22 from your IP; verify key at $SSHKey"
        return $false
    }
}

function Test-NginxHealth {
    Write-Section "NGINX"
    $status = Invoke-SSH "systemctl is-active nginx 2>&1"
    if ($status.Trim() -eq "active") {
        Write-OK "nginx is running"
    } else {
        Write-Fail "nginx is NOT running (status: $($status.Trim()))"
        Add-Finding "CRITICAL" "Nginx" "nginx is not running" "sudo systemctl start nginx"
    }

    $configTest = Invoke-SSH "sudo nginx -t 2>&1"
    if ($configTest -match "successful") {
        Write-OK "nginx config is valid"
    } else {
        Write-Fail "nginx config error: $configTest"
        Add-Finding "CRITICAL" "Nginx" "Config syntax error" "Review /etc/nginx/sites-available/ethiopian-business"
    }

    $listening = Invoke-SSH "sudo ss -tlnp | grep ':80 ' 2>&1"
    if ($listening) { Write-OK "Port 80 is listening" }
    else {
        Write-Fail "Nothing listening on port 80"
        Add-Finding "CRITICAL" "Nginx" "Port 80 not open" "sudo systemctl restart nginx"
    }
}

function Test-SupervisorHealth {
    Write-Section "SUPERVISOR / GUNICORN"
    $supStatus = Invoke-SSH "sudo supervisorctl status ethiopian-business 2>&1"
    Write-Info "Supervisor status: $($supStatus.Trim())"

    if ($supStatus -match "RUNNING") {
        Write-OK "gunicorn is RUNNING via supervisor"
    } elseif ($supStatus -match "FATAL") {
        Write-Fail "gunicorn is FATAL — crashed on startup"
        Add-Finding "CRITICAL" "Gunicorn" "Process in FATAL state" "Check logs below; likely ImportError or missing dependency"
    } elseif ($supStatus -match "STOPPED") {
        Write-Warn "gunicorn is STOPPED"
        Add-Finding "WARNING" "Gunicorn" "Process stopped" "sudo supervisorctl start ethiopian-business"
    } else {
        Write-Warn "Unexpected supervisor status: $supStatus"
    }

    $port = Invoke-SSH "sudo ss -tlnp | grep ':5000 ' 2>&1"
    if ($port) {
        Write-OK "Port 5000 is listening"
    } else {
        Write-Fail "Nothing listening on port 5000"
        Add-Finding "CRITICAL" "Gunicorn" "Port 5000 not open — app not running" "Fix app crash first, then: sudo supervisorctl restart ethiopian-business"
    }
}

function Test-FlaskAppHealth {
    param([string]$ALB_DNS)
    Write-Section "FLASK APPLICATION"

    # Test from inside the server (bypasses nginx/ALB)
    $localHealth = Invoke-SSH "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:5000/health 2>&1"
    if ($localHealth.Trim() -eq "200") {
        Write-OK "Flask /health returns 200 locally"
    } else {
        Write-Fail "Flask /health returns $($localHealth.Trim()) locally"
        Add-Finding "CRITICAL" "Flask" "App not responding on localhost:5000" "Check gunicorn logs and Python import errors"
    }

    # Test through nginx
    $nginxHealth = Invoke-SSH "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost/health 2>&1"
    if ($nginxHealth.Trim() -eq "200") {
        Write-OK "nginx → Flask /health returns 200"
    } else {
        Write-Warn "nginx → Flask returns $($nginxHealth.Trim())"
    }

    # Test through ALB (external)
    if ($ALB_DNS) {
        try {
            $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://$ALB_DNS/health" -TimeoutSec 10 -ErrorAction Stop
            Write-OK "ALB → /health returns $($resp.StatusCode)"
        } catch {
            $code = $_.Exception.Response.StatusCode.value__
            Write-Fail "ALB → /health returns $code"
            if ($code -eq 502) {
                Add-Finding "CRITICAL" "ALB" "502 Bad Gateway — gunicorn not running" "Fix app crash, then ALB will recover automatically"
            } elseif ($code -eq 503) {
                Add-Finding "WARNING" "ALB" "503 — target unhealthy, draining" "Wait for health check to pass after fixing app"
            }
        }
    }
}

function Test-DatabaseHealth {
    Write-Section "DATABASE (RDS)"
    $pgReady = Invoke-SSH "pg_isready -h `$(grep DATABASE_URL /opt/ethiopian-business/.env 2>/dev/null | sed 's/.*@//;s/:.*//') -p 5432 2>&1"
    if ($pgReady -match "accepting connections") {
        Write-OK "PostgreSQL is accepting connections"
    } else {
        Write-Warn "PostgreSQL check: $($pgReady.Trim())"
        Add-Finding "WARNING" "RDS" "Database not reachable from EC2" "Check DB security group and VPC routing; app may still work with parquet storage"
    }
}

function Test-DiskSpace {
    Write-Section "DISK SPACE"
    $df = Invoke-SSH "df -h / | tail -1 2>&1"
    Write-Info "Root disk: $($df.Trim())"
    if ($df -match "(\d+)%") {
        $pct = [int]$Matches[1]
        if ($pct -gt 90) {
            Write-Fail "Disk usage at ${pct}%"
            Add-Finding "CRITICAL" "Disk" "Disk usage ${pct}%" "Clean /var/log or increase EBS volume"
        } elseif ($pct -gt 75) {
            Write-Warn "Disk usage at ${pct}%"
        } else {
            Write-OK "Disk usage normal (${pct}%)"
        }
    }
}

function Test-MemoryCPU {
    Write-Section "MEMORY & CPU"
    $mem = Invoke-SSH "free -m | head -2 2>&1"
    Write-Info $mem
    $load = Invoke-SSH "uptime 2>&1"
    Write-Info "Load: $($load.Trim())"
    $oom = Invoke-SSH "dmesg | grep -i 'out of memory' | tail -3 2>&1"
    if ($oom -and $oom -notmatch "^$") {
        Write-Fail "OOM killer events detected!"
        Write-Info $oom
        Add-Finding "CRITICAL" "Memory" "OOM events found" "Reduce gunicorn workers or increase instance size"
    } else {
        Write-OK "No OOM events"
    }
}

function Test-S3Access {
    param([string]$BucketName)
    Write-Section "S3 BUCKET"
    if (-not $BucketName) { Write-Warn "No bucket name available"; return }
    try {
        $out = aws s3 ls "s3://$BucketName" --region $Region 2>&1
        Write-OK "S3 bucket accessible: $BucketName"
    } catch {
        Write-Fail "S3 access failed: $_"
        Add-Finding "WARNING" "S3" "Cannot list bucket $BucketName" "Check IAM role and bucket policy"
    }
}

function Test-TargetGroupHealth {
    Write-Section "ALB TARGET GROUP"
    try {
        $tgArn = aws elbv2 describe-target-groups --region $Region --names "ethiopian-business-mvp-tg" --query 'TargetGroups[0].TargetGroupArn' --output text 2>$null
        if ($tgArn) {
            $health = aws elbv2 describe-target-health --region $Region --target-group-arn $tgArn --output json 2>$null | ConvertFrom-Json
            foreach ($t in $health.TargetHealthDescriptions) {
                $state = $t.TargetHealth.State
                $reason = $t.TargetHealth.Reason
                $desc = $t.TargetHealth.Description
                if ($state -eq "healthy") {
                    Write-OK "Target $($t.Target.Id):$($t.Target.Port) is HEALTHY"
                } else {
                    Write-Fail "Target $($t.Target.Id):$($t.Target.Port) is $state — $reason — $desc"
                    Add-Finding "CRITICAL" "ALB" "Target unhealthy: $reason" "Fix the app so /health returns 200"
                }
            }
        } else {
            Write-Warn "Target group not found"
        }
    } catch {
        Write-Warn "Could not query target group: $_"
    }
}

function Test-SecurityGroups {
    Write-Section "SECURITY GROUPS"
    try {
        $instanceId = Invoke-SSH "curl -s --max-time 3 http://169.254.169.254/latest/meta-data/instance-id 2>&1"
        if ($instanceId -match "^i-") {
            $sgs = aws ec2 describe-instances --region $Region --instance-ids $instanceId.Trim() --query 'Reservations[0].Instances[0].SecurityGroups[*].[GroupId,GroupName]' --output text 2>$null
            Write-Info "Security groups: $sgs"
            # Check inbound 80 is open
            foreach ($line in ($sgs -split "`n")) {
                $sgId = ($line -split "\s+")[0]
                if ($sgId -match "^sg-") {
                    $rules = aws ec2 describe-security-group-rules --region $Region --filters "Name=group-id,Values=$sgId" --query 'SecurityGroupRules[?IsEgress==`false`].[FromPort,ToPort,CidrIpv4]' --output text 2>$null
                    if ($rules -match "\b80\b") { Write-OK "Port 80 open in $sgId" }
                    if ($rules -match "\b22\b") { Write-OK "Port 22 open in $sgId" }
                }
            }
        }
    } catch {
        Write-Warn "Could not check security groups: $_"
    }
}

# ═══════════════════════════════════════════════════════════════════
# LOG COLLECTION
# ═══════════════════════════════════════════════════════════════════

function Get-AllLogs {
    Write-Section "COLLECTING ALL AWS LOGS"
    $logFile = Join-Path $logDir "logs_${timestamp}.txt"
    Write-Info "Saving to $logFile"

    $logCommands = @(
        @{ Name = "SUPERVISOR LOG";          Cmd = "sudo tail -80 /var/log/supervisor/supervisord.log 2>&1" },
        @{ Name = "APP STDOUT (supervisor)"; Cmd = "sudo tail -150 /var/log/ethiopian-business.log 2>&1" },
        @{ Name = "APP ERROR LOG";           Cmd = "sudo tail -100 /var/log/ethiopian-business-error.log 2>&1" },
        @{ Name = "APP ACCESS LOG";          Cmd = "sudo tail -50 /var/log/ethiopian-business-access.log 2>&1" },
        @{ Name = "NGINX ERROR LOG";         Cmd = "sudo tail -80 /var/log/nginx/error.log 2>&1" },
        @{ Name = "NGINX ACCESS LOG";        Cmd = "sudo tail -30 /var/log/nginx/access.log 2>&1" },
        @{ Name = "CLOUD-INIT OUTPUT";       Cmd = "sudo tail -150 /var/log/cloud-init-output.log 2>&1" },
        @{ Name = "USER_DATA LOG";           Cmd = "sudo tail -150 /var/log/user_data.log 2>&1" },
        @{ Name = "SYSLOG (app errors)";     Cmd = "sudo grep -i 'ethiopian\|gunicorn\|supervisor' /var/log/syslog | tail -40 2>&1" },
        @{ Name = "DMESG (kernel/OOM)";      Cmd = "sudo dmesg | tail -30 2>&1" },
        @{ Name = "JOURNALCTL nginx";        Cmd = "sudo journalctl -u nginx --no-pager -n 30 2>&1" },
        @{ Name = "PIP PACKAGES";            Cmd = "sudo -u businessapp /opt/ethiopian-business/venv/bin/pip list 2>&1" },
        @{ Name = "PYTHON PATH TEST";        Cmd = "sudo -u businessapp /opt/ethiopian-business/venv/bin/python -c 'import sys; print(chr(10).join(sys.path))' 2>&1" },
        @{ Name = "ENV FILE (redacted)";     Cmd = "sudo cat /opt/ethiopian-business/.env 2>&1 | sed 's/=.*/=***REDACTED***/' " },
        @{ Name = "SUPERVISOR CONF";         Cmd = "sudo cat /etc/supervisor/conf.d/ethiopian-business.conf 2>&1" },
        @{ Name = "NGINX SITE CONF";         Cmd = "sudo cat /etc/nginx/sites-available/ethiopian-business 2>&1" },
        @{ Name = "RUN_PRODUCTION.PY";       Cmd = "cat /opt/ethiopian-business/run_production.py 2>&1" },
        @{ Name = "DEPLOY COMPLETE MARKER";  Cmd = "ls -la /opt/ethiopian-business/.deploy_complete 2>&1" },
        @{ Name = "APP DIRECTORY LISTING";   Cmd = "ls -la /opt/ethiopian-business/ 2>&1" },
        @{ Name = "WEB DIRECTORY LISTING";   Cmd = "ls -la /opt/ethiopian-business/web/ 2>&1" },
        @{ Name = "DISK USAGE";              Cmd = "df -h 2>&1" },
        @{ Name = "MEMORY";                  Cmd = "free -m 2>&1" },
        @{ Name = "PROCESSES (gunicorn)";    Cmd = "ps aux | grep gunicorn 2>&1" },
        @{ Name = "OPEN PORTS";              Cmd = "sudo ss -tlnp 2>&1" }
    )

    $allOutput = "Ethiopian Business Management System — Full Log Dump`n"
    $allOutput += "Timestamp: $timestamp`n"
    $allOutput += "Server: $script:ip`n"
    $allOutput += ("=" * 80) + "`n"

    foreach ($log in $logCommands) {
        Write-Host "  Collecting $($log.Name)..." -NoNewline
        $out = Invoke-SSH $log.Cmd
        $allOutput += "`n`n=== $($log.Name) ===`n$out`n"

        # Scan for common errors
        if ($out -match "ModuleNotFoundError|ImportError") {
            Write-Fail " IMPORT ERROR FOUND"
            $match = ($out -split "`n" | Select-String "ModuleNotFoundError|ImportError" | Select-Object -First 3) -join "`n"
            Add-Finding "CRITICAL" $log.Name "Python import error: $match" "Check sys.path and pip install; ensure web/ is on sys.path"
        } elseif ($out -match "Permission denied") {
            Write-Warn " PERMISSION ERROR"
            Add-Finding "WARNING" $log.Name "Permission denied errors found" "Check file ownership: chown -R businessapp:businessapp /opt/ethiopian-business"
        } elseif ($out -match "Address already in use") {
            Write-Warn " PORT CONFLICT"
            Add-Finding "CRITICAL" $log.Name "Port already in use" "Kill conflicting process: sudo fuser -k 5000/tcp"
        } elseif ($out -match "No such file or directory" -and $log.Name -notmatch "ERROR LOG|ACCESS LOG") {
            Write-Warn " MISSING FILE"
        } else {
            Write-Host " done" -ForegroundColor DarkGray
        }
    }

    $allOutput | Out-File -FilePath $logFile -Encoding utf8
    Write-OK "All logs saved to $logFile"
    return $logFile
}

# ═══════════════════════════════════════════════════════════════════
# DEEP DIAGNOSIS — PATTERN MATCHING
# ═══════════════════════════════════════════════════════════════════

function Invoke-DeepDiagnosis {
    Write-Section "DEEP DIAGNOSIS"

    # 1. Check if run_production.py has the sys.path fix
    $rpContent = Invoke-SSH "cat /opt/ethiopian-business/run_production.py 2>&1"
    if ($rpContent -match "os\.path\.join\(project_root,\s*'web'\)") {
        Write-OK "run_production.py has the web/ sys.path fix"
    } else {
        Write-Fail "run_production.py is MISSING the web/ sys.path fix"
        Add-Finding "CRITICAL" "run_production.py" "Missing sys.path.insert for web/ directory" "Redeploy or patch run_production.py (see Fix action)"
    }

    # 2. Check if venv has all required packages
    $packages = Invoke-SSH "sudo -u businessapp /opt/ethiopian-business/venv/bin/pip list --format=columns 2>&1"
    foreach ($pkg in @('flask','gunicorn','python-dotenv','bcrypt','flask-wtf','pandas','pyarrow','openpyxl')) {
        if ($packages -match "(?i)$pkg") { Write-OK "pip: $pkg installed" }
        else {
            Write-Fail "pip: $pkg MISSING"
            Add-Finding "CRITICAL" "Dependencies" "$pkg not installed" "sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install $pkg"
        }
    }

    # 3. Try a dry-run import
    Write-Info "Testing Python imports..."
    $importTest = Invoke-SSH @"
cd /opt/ethiopian-business && sudo -u businessapp /opt/ethiopian-business/venv/bin/python -c "
import sys, os
project_root = '/opt/ethiopian-business'
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, 'web'))
try:
    from web.app import app
    print('IMPORT_OK')
except Exception as e:
    print(f'IMPORT_FAIL: {e}')
" 2>&1
"@
    if ($importTest -match "IMPORT_OK") {
        Write-OK "Flask app imports successfully"
    } else {
        Write-Fail "Flask app import FAILED: $importTest"
        Add-Finding "CRITICAL" "Flask" "App fails to import: $importTest" "Fix the reported import/module error"
    }

    # 4. Check .env has required keys
    $envKeys = Invoke-SSH "grep -c 'FLASK_SECRET_KEY\|DEFAULT_ADMIN_PASSWORD\|DATABASE_URL' /opt/ethiopian-business/.env 2>&1"
    if ([int]$envKeys -ge 3) {
        Write-OK ".env has all required keys (FLASK_SECRET_KEY, DEFAULT_ADMIN_PASSWORD, DATABASE_URL)"
    } else {
        Write-Warn ".env may be missing keys (found $envKeys of 3 expected)"
        Add-Finding "WARNING" "Config" ".env file incomplete" "Regenerate .env with all required keys"
    }

    # 5. Check supervisor can see the conf
    $supConf = Invoke-SSH "sudo supervisorctl avail 2>&1"
    if ($supConf -match "ethiopian-business") {
        Write-OK "Supervisor knows about ethiopian-business"
    } else {
        Write-Fail "Supervisor doesn't see ethiopian-business config"
        Add-Finding "CRITICAL" "Supervisor" "Config not loaded" "sudo supervisorctl reread && sudo supervisorctl update"
    }

    # 6. Check if gunicorn worker dies with traceback
    $supLog = Invoke-SSH "sudo tail -30 /var/log/ethiopian-business.log 2>&1"
    if ($supLog -match "Traceback") {
        Write-Fail "Python traceback found in app log!"
        $tb = ($supLog -split "`n" | Select-String -Pattern "Traceback|Error|File " | Select-Object -Last 10) -join "`n"
        Write-Info $tb
        Add-Finding "CRITICAL" "Flask" "Python traceback in logs" "Read the traceback above and fix the code error"
    }

    # 7. Check for port conflicts
    $port5000 = Invoke-SSH "sudo ss -tlnp | grep ':5000 ' 2>&1"
    $port5000Lines = ($port5000 -split "`n" | Where-Object { $_ -match ':5000' }).Count
    if ($port5000Lines -gt 1) {
        Write-Fail "Multiple processes on port 5000!"
        Add-Finding "CRITICAL" "Port" "Port conflict on 5000" "sudo fuser -k 5000/tcp; sudo supervisorctl restart ethiopian-business"
    }

    # 8. Check systemd/supervisor conflict
    $sysdActive = Invoke-SSH "systemctl is-active ethiopian-business 2>&1"
    if ($sysdActive.Trim() -eq "active") {
        Write-Fail "systemd ethiopian-business is ACTIVE — conflicts with supervisor!"
        Add-Finding "CRITICAL" "Startup" "Both systemd and supervisor managing gunicorn" "sudo systemctl stop ethiopian-business; sudo systemctl disable ethiopian-business"
    } else {
        Write-OK "systemd service correctly disabled (supervisor manages gunicorn)"
    }
}

# ═══════════════════════════════════════════════════════════════════
# AUTO-FIX — COMMON ISSUES
# ═══════════════════════════════════════════════════════════════════

function Invoke-AutoFix {
    Write-Section "AUTO-FIX (applying common fixes)"

    # Fix 1: Patch run_production.py with sys.path for web/
    Write-Info "Fix 1: Ensuring run_production.py has web/ on sys.path..."
    Invoke-SSH @"
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
"@ | Out-Null
    Invoke-SSH "sudo chown businessapp:businessapp /opt/ethiopian-business/run_production.py" | Out-Null
    Write-OK "run_production.py patched"

    # Fix 2: Install missing pip packages
    Write-Info "Fix 2: Ensuring all pip packages are installed..."
    Invoke-SSH "sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install -q gunicorn python-dotenv bcrypt flask-wtf pandas pyarrow openpyxl 2>&1" | Out-Null
    Invoke-SSH "sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install -q -r /opt/ethiopian-business/requirements.txt 2>&1" | Out-Null
    Write-OK "pip packages ensured"

    # Fix 3: Fix permissions
    Write-Info "Fix 3: Fixing file ownership..."
    Invoke-SSH "sudo chown -R businessapp:businessapp /opt/ethiopian-business" | Out-Null
    Write-OK "Ownership fixed"

    # Fix 4: Disable systemd service if active
    $sysdActive = Invoke-SSH "systemctl is-active ethiopian-business 2>&1"
    if ($sysdActive.Trim() -eq "active") {
        Write-Info "Fix 4: Disabling conflicting systemd service..."
        Invoke-SSH "sudo systemctl stop ethiopian-business; sudo systemctl disable ethiopian-business" | Out-Null
        Write-OK "systemd service disabled"
    }

    # Fix 5: Kill anything on port 5000 and restart supervisor
    Write-Info "Fix 5: Restarting application..."
    Invoke-SSH "sudo fuser -k 5000/tcp 2>/dev/null; sleep 2" | Out-Null
    Invoke-SSH "sudo supervisorctl reread; sudo supervisorctl update" | Out-Null
    Invoke-SSH "sudo supervisorctl restart ethiopian-business" | Out-Null
    Start-Sleep -Seconds 5
    
    # Verify
    $status = Invoke-SSH "sudo supervisorctl status ethiopian-business 2>&1"
    Write-Info "Supervisor status: $($status.Trim())"
    if ($status -match "RUNNING") {
        Write-OK "Application is now RUNNING!"
    } else {
        Write-Fail "Application still not running after fixes"
        Write-Info "Checking error log..."
        $errLog = Invoke-SSH "sudo tail -30 /var/log/ethiopian-business.log 2>&1"
        Write-Host $errLog -ForegroundColor DarkGray
    }

    # Fix 6: Restart nginx just in case
    Invoke-SSH "sudo systemctl restart nginx" | Out-Null
    Write-OK "nginx restarted"

    # Final health check
    Start-Sleep -Seconds 3
    $health = Invoke-SSH "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:5000/health 2>&1"
    if ($health.Trim() -eq "200") {
        Write-OK "Health check PASSED — app is serving on port 5000"
    } else {
        Write-Fail "Health check still failing (HTTP $($health.Trim()))"
        Write-Info "Run '.\diagnose.ps1 -Action Logs' to see detailed error output"
    }
}

# ═══════════════════════════════════════════════════════════════════
# WATCH MODE — CONTINUOUS MONITORING
# ═══════════════════════════════════════════════════════════════════

function Start-Watch {
    Write-Section "CONTINUOUS MONITORING (Ctrl+C to stop)"
    Write-Info "Checking every ${WatchInterval}s..."
    try {
        while ($true) {
            $ts = Get-Date -Format 'HH:mm:ss'
            $sup = (Invoke-SSH "sudo supervisorctl status ethiopian-business 2>&1").Trim()
            $localHC = (Invoke-SSH "curl -s -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:5000/health 2>&1").Trim()
            $mem = (Invoke-SSH "free -m | awk '/Mem/{printf \"%.0f%%\", \`$3/\`$2*100}' 2>&1").Trim()
            $cpu = (Invoke-SSH "top -bn1 | awk '/Cpu/{printf \"%.0f%%\", 100-\`$8}' 2>&1").Trim()
            $disk = (Invoke-SSH "df -h / | awk 'NR==2{print \`$5}' 2>&1").Trim()

            $color = if ($localHC -eq '200') { 'Green' } else { 'Red' }
            Write-Host "[$ts] sup=$sup | health=$localHC | mem=$mem | cpu=$cpu | disk=$disk" -ForegroundColor $color

            Start-Sleep -Seconds $WatchInterval
        }
    } catch {
        Write-Info "Monitoring stopped."
    }
}

# ═══════════════════════════════════════════════════════════════════
# FINDINGS REPORT
# ═══════════════════════════════════════════════════════════════════

function Show-FindingsReport {
    Write-Section "FINDINGS SUMMARY"
    if ($findings.Count -eq 0) {
        Write-OK "No issues found — everything looks healthy!"
        return
    }

    $criticals = $findings | Where-Object { $_ -match "^\[CRITICAL\]" }
    $warnings  = $findings | Where-Object { $_ -match "^\[WARNING\]" }

    if ($criticals) {
        Write-Host "`n  CRITICAL ISSUES ($($criticals.Count)):" -ForegroundColor Red
        foreach ($f in $criticals) {
            $parts = $f -split '\|'
            Write-Host "    $($parts[0].Trim())" -ForegroundColor Red
            if ($parts.Count -gt 1) { Write-Host "      → $($parts[1].Trim())" -ForegroundColor Yellow }
        }
    }
    if ($warnings) {
        Write-Host "`n  WARNINGS ($($warnings.Count)):" -ForegroundColor Yellow
        foreach ($f in $warnings) {
            $parts = $f -split '\|'
            Write-Host "    $($parts[0].Trim())" -ForegroundColor Yellow
            if ($parts.Count -gt 1) { Write-Host "      → $($parts[1].Trim())" -ForegroundColor DarkYellow }
        }
    }

    # Save report
    $reportContent = "Diagnostic Report — $timestamp`n" + ("=" * 60) + "`n"
    $reportContent += ($findings -join "`n") + "`n"
    $reportContent | Out-File -FilePath $reportFile -Encoding utf8
    Write-Info "Report saved to $reportFile"

    if ($criticals) {
        Write-Host "`n  TIP: Run '.\diagnose.ps1 -Action Fix' to auto-fix common issues." -ForegroundColor Cyan
    }
}

# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

Write-Host "`n╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  Ethiopian Business Management System — AWS Diagnostics     ║" -ForegroundColor Cyan
Write-Host "║  Action: $($Action.PadRight(52))║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

$script:ip = Get-ServerIP
Write-Info "Target server: $script:ip"

$outputs = Get-TerraformOutputs

switch ($Action) {
    'Health' {
        if (-not (Test-SSHConnectivity)) { Show-FindingsReport; exit 1 }
        Test-NginxHealth
        Test-SupervisorHealth
        Test-FlaskAppHealth -ALB_DNS $outputs['load_balancer_dns']
        Test-TargetGroupHealth
        Show-FindingsReport
    }
    'Logs' {
        if (-not (Test-SSHConnectivity)) { exit 1 }
        Get-AllLogs
    }
    'Diagnose' {
        if (-not (Test-SSHConnectivity)) { Show-FindingsReport; exit 1 }
        Test-NginxHealth
        Test-SupervisorHealth
        Test-FlaskAppHealth -ALB_DNS $outputs['load_balancer_dns']
        Invoke-DeepDiagnosis
        Show-FindingsReport
    }
    'Fix' {
        if (-not (Test-SSHConnectivity)) { exit 1 }
        Invoke-AutoFix
        Show-FindingsReport
    }
    'Watch' {
        if (-not (Test-SSHConnectivity)) { exit 1 }
        Start-Watch
    }
    'All' {
        if (-not (Test-SSHConnectivity)) { Show-FindingsReport; exit 1 }
        Test-NginxHealth
        Test-SupervisorHealth
        Test-FlaskAppHealth -ALB_DNS $outputs['load_balancer_dns']
        Test-DatabaseHealth
        Test-DiskSpace
        Test-MemoryCPU
        Test-S3Access -BucketName $outputs['s3_bucket_name']
        Test-TargetGroupHealth
        Test-SecurityGroups
        Get-AllLogs
        Invoke-DeepDiagnosis
        Show-FindingsReport
    }
}
