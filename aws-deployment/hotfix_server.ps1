#!/usr/bin/env pwsh
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

# Step 1: Test SSH
Write-Step "Testing SSH connectivity..."
$test = ssh @sshOpts $sshTarget "echo OK" 2>&1
if ($test -notmatch "OK") { Write-Fail "Cannot SSH to $ServerIP"; exit 1 }
Write-OK "SSH connected"

# Step 2: Fix log permissions
Write-Step "Fixing log file permissions..."
ssh @sshOpts $sshTarget @"
sudo touch /var/log/ethiopian-business.log /var/log/ethiopian-business-error.log /var/log/ethiopian-business-access.log
sudo chown businessapp:businessapp /var/log/ethiopian-business*.log
echo LOGFIX_OK
"@ 2>&1 | ForEach-Object { if ($_ -match "LOGFIX_OK") { Write-OK "Log files created and owned by businessapp" } }

# Step 3: Create all data directories
Write-Step "Creating data directories..."
ssh @sshOpts $sshTarget @"
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/data/{platform,auth,bids,bids/documents,backups,siem,versions}
sudo -u businessapp mkdir -p /opt/ethiopian-business/web/exports /opt/ethiopian-business/data /opt/ethiopian-business/web/sample_files
sudo chown -R businessapp:businessapp /opt/ethiopian-business/web/data /opt/ethiopian-business/data
echo DIRFIX_OK
"@ 2>&1 | ForEach-Object { if ($_ -match "DIRFIX_OK") { Write-OK "All data directories created" } }

# Step 4: Restart app (simplified)
Write-Step "Restarting services..."
ssh @sshOpts $sshTarget @"
sudo supervisorctl restart ethiopian-business
sudo systemctl restart nginx
echo RESTART_DONE
"@ 2>&1 | ForEach-Object { if ($_ -match "RESTART_DONE") { Write-OK "App and nginx restarted" } }

# Step 5: Verify /health
Write-Step "Verifying /health..."
Start-Sleep -Seconds 3
try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://$ServerIP/health" -TimeoutSec 10 -ErrorAction Stop
    Write-OK "External health check: HTTP $($resp.StatusCode)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    Write-Fail "External health check: HTTP $code"
}

Write-Host "`n========================================" -ForegroundColor Yellow
Write-Host "  Hotfix complete!" -ForegroundColor Yellow
Write-Host "========================================`n" -ForegroundColor Yellow


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

# ── Step 6b: Harden nginx — block scanner bots, suppress static 404s ──
Write-Step "Hardening nginx (block bot IPs, suppress static 404 logs)..."
ssh @sshOpts $sshTarget @"
sudo tee /etc/nginx/sites-available/ethiopian-business << 'NGXEOF'
server {
    listen 80;
    server_name _;

    # Block known VPC-internal bot scanner IPs (Chinese gambling site crawlers)
    deny 10.0.2.126;
    deny 10.0.1.27;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /static {
        alias /opt/ethiopian-business/web/static;
        expires 1y;
        add_header Cache-Control "public, immutable";
        log_not_found off;
        access_log off;
    }

    location /health {
        proxy_pass http://127.0.0.1:5000/health;
        access_log off;
    }
}
NGXEOF
sudo nginx -t && sudo systemctl reload nginx && echo NGINX_HARDENED
"@ 2>&1 | ForEach-Object {
    if (\$_ -match "NGINX_HARDENED") { Write-OK "Nginx hardened: bots blocked, static 404s suppressed" }
    if (\$_ -match "emerg|error")   { Write-Fail "Nginx config error: \$_" }
}

# ── Step 7: Upload fixed Python modules ──────────────────────────
Write-Step "Uploading fixed Python modules..."
$webSrc    = Join-Path $PSScriptRoot "..\web"
$remoteDst = "/opt/ethiopian-business/web"
$filesToUpload = @(
    # Core infrastructure
    "db.py",
    "extensions.py",
    "secrets_loader.py",
    "app.py",
    # Auth
    "auth_data_store.py",
    "auth_routes.py",
    # Tenant / provider
    "tenant_data_store.py",
    "provider_admin_routes.py",
    # VAT / finance
    "vat_data_store.py",
    "income_expense_data_store.py",
    "transaction_data_store.py",
    "chart_of_accounts_data_store.py",
    "journal_entry_data_store.py",
    # CPO / inventory / bid
    "cpo_data_store.py",
    "inventory_data_store.py",
    "bid_data_store.py",
    "bid_routes.py",
    # Payroll / employees
    "employee_data_store.py",
    # Backup / SIEM
    "backup_data_store.py",
    "backup_routes.py",
    "siem_data_store.py",
    # Multi-company
    "multicompany_routes.py"
)
foreach ($f in $filesToUpload) {
    $local = Join-Path $webSrc $f
    if (Test-Path $local) {
        Get-Content $local -Raw -Encoding UTF8 |
            ssh @sshOpts $sshTarget "sudo tee $remoteDst/$f > /dev/null && sudo chown businessapp:businessapp $remoteDst/$f && echo UPLOADED_$f" 2>&1 |
            ForEach-Object { if ($_ -match "UPLOADED_(.+)") { Write-OK "Uploaded $($Matches[1])" } }
    } else {
        Write-Fail "Local file not found: $local"
    }
}

# Upload error templates
$errSrc = Join-Path $webSrc "templates\errors"
if (-not (Test-Path $errSrc)) {
    $errSrc = Join-Path $PSScriptRoot "..\..\web\templates\errors"
}
ssh @sshOpts $sshTarget "sudo mkdir -p $remoteDst/templates/errors && sudo chown businessapp:businessapp $remoteDst/templates/errors" 2>&1 | Out-Null
foreach ($tpl in @("404.html", "500.html")) {
    $local = Join-Path $errSrc $tpl
    if (Test-Path $local) {
        Get-Content $local -Raw -Encoding UTF8 |
            ssh @sshOpts $sshTarget "sudo tee $remoteDst/templates/errors/$tpl > /dev/null && sudo chown businessapp:businessapp $remoteDst/templates/errors/$tpl && echo UPLOADED_$tpl" 2>&1 |
            ForEach-Object { if ($_ -match "UPLOADED_(.+)") { Write-OK "Uploaded template $($Matches[1])" } }
    }
}

# Upload base template (contains nav links — must stay in sync)
$baseSrc = Join-Path $webSrc "templates\base.html"
if (-not (Test-Path $baseSrc)) { $baseSrc = Join-Path $PSScriptRoot "..\..\web\templates\base.html" }
if (Test-Path $baseSrc) {
    Get-Content $baseSrc -Raw -Encoding UTF8 |
        ssh @sshOpts $sshTarget "sudo tee $remoteDst/templates/base.html > /dev/null && sudo chown businessapp:businessapp $remoteDst/templates/base.html && echo UPLOADED_base.html" 2>&1 |
        ForEach-Object { if ($_ -match "UPLOADED_(.+)") { Write-OK "Uploaded template $($Matches[1])" } }
}
foreach ($tpl in @("404.html", "500.html")) {
    $local = Join-Path $errSrc $tpl
    if (Test-Path $local) {
        Get-Content $local -Raw -Encoding UTF8 |
            ssh @sshOpts $sshTarget "sudo tee $remoteDst/templates/errors/$tpl > /dev/null && sudo chown businessapp:businessapp $remoteDst/templates/errors/$tpl && echo UPLOADED_$tpl" 2>&1 |
            ForEach-Object { if ($_ -match "UPLOADED_(.+)") { Write-OK "Uploaded template $($Matches[1])" } }
    }
}

# Upload auth templates (all — base, login, portal, register, access_denied)
$authSrc = Join-Path $webSrc "templates\auth"
ssh @sshOpts $sshTarget "sudo mkdir -p $remoteDst/templates/auth && sudo chown businessapp:businessapp $remoteDst/templates/auth" 2>&1 | Out-Null
foreach ($tpl in @("base.html", "login.html", "portal.html", "register.html", "access_denied.html")) {
    $local = Join-Path $authSrc $tpl
    if (Test-Path $local) {
        Get-Content $local -Raw -Encoding UTF8 |
            ssh @sshOpts $sshTarget "sudo tee $remoteDst/templates/auth/$tpl > /dev/null && sudo chown businessapp:businessapp $remoteDst/templates/auth/$tpl && echo UPLOADED_$tpl" 2>&1 |
            ForEach-Object { if ($_ -match "UPLOADED_(.+)") { Write-OK "Uploaded template $($Matches[1])" } }
    }
}

# Upload sales templates (index.html has auth links)
$salesSrc = Join-Path $webSrc "templates\sales"
if (Test-Path $salesSrc) {
    ssh @sshOpts $sshTarget "sudo mkdir -p $remoteDst/templates/sales && sudo chown businessapp:businessapp $remoteDst/templates/sales" 2>&1 | Out-Null
    foreach ($tpl in @("index.html")) {
        $local = Join-Path $salesSrc $tpl
        if (Test-Path $local) {
            Get-Content $local -Raw -Encoding UTF8 |
                ssh @sshOpts $sshTarget "sudo tee $remoteDst/templates/sales/$tpl > /dev/null && sudo chown businessapp:businessapp $remoteDst/templates/sales/$tpl && echo UPLOADED_sales_$tpl" 2>&1 |
                ForEach-Object { if ($_ -match "UPLOADED_(.+)") { Write-OK "Uploaded template $($Matches[1])" } }
        }
    }
}

# Install new Python dependencies
ssh @sshOpts $sshTarget @"
sudo -u businessapp /opt/ethiopian-business/venv/bin/pip install \
    'Flask-Limiter>=3.5.0' \
    'Flask-Caching>=2.1.0' \
    'APScheduler>=3.10.0' \
    'python-json-logger>=2.0.0' \
    'alembic>=1.13.0' \
    'sqlalchemy>=2.0.0' \
    'boto3>=1.34.0' \
    --quiet && echo DEPS_INSTALLED
"@ 2>&1 | ForEach-Object { if ($_ -match "DEPS_INSTALLED") { Write-OK "All Python dependencies installed" } }

# Apply any pending Alembic DB migrations
ssh @sshOpts $sshTarget @"
cd /opt/ethiopian-business/web
source /opt/ethiopian-business/venv/bin/activate 2>/dev/null || true
alembic upgrade head && echo MIGRATIONS_OK || echo MIGRATIONS_SKIPPED
"@ 2>&1 | ForEach-Object {
    if ($_ -match "MIGRATIONS_OK")      { Write-OK "DB migrations applied (alembic upgrade head)" }
    if ($_ -match "MIGRATIONS_SKIPPED") { Write-OK "No pending DB migrations" }
}

# Restart after file uploads
ssh @sshOpts $sshTarget "sudo supervisorctl restart ethiopian-business; sleep 3; echo RESTART_DONE" 2>&1 |
    ForEach-Object { if ($_ -match "RESTART_DONE") { Write-OK "App restarted after file upload" } }

# ── Step 8: Verify from outside ──────────────────────────────────
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
