param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,
    [string]$SSHKey = "$HOME\.ssh\id_rsa",
    [string]$LocalWebPath = "C:\Users\info\Documents\GitHub\accounting\web",
    [string]$RemotePath = "/opt/ethiopian-business/web",
    [int]$RetryCount = 5,
    [int]$RetryDelaySec = 10
)

function Write-OK   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Step { param($m) Write-Host "`n=> $m" -ForegroundColor Cyan }
function Write-Warn { param($m) Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "  [FAIL] $m" -ForegroundColor Red }

$sshTarget = "ubuntu@$ServerIP"
$sshOpts   = @('-o','StrictHostKeyChecking=no','-o','ConnectTimeout=5','-i',$SSHKey)

# ── Step 0: Check SSH connectivity ─────────────────────────────
$connected = $false
for ($i=1; $i -le $RetryCount; $i++) {
    Write-Step "Testing SSH connectivity (attempt $i/$RetryCount)..."
    try {
        $test = ssh @sshOpts $sshTarget "echo OK" 2>&1
        if ($test -match "OK") {
            Write-OK "SSH connected to $ServerIP"
            $connected = $true
            break
        }
    } catch {}
    Write-Warn "SSH not available yet, retrying in $RetryDelaySec seconds..."
    Start-Sleep -Seconds $RetryDelaySec
}

if (-not $connected) {
    Write-Fail "Cannot connect to $ServerIP via SSH. Check security group, firewall, or instance status."
    exit 1
}

# ── Step 1: Create tarball of web folder ───────────────────────
Write-Step "Creating tarball..."
$tarFile = Join-Path $env:TEMP "web.tar.gz"
if (Test-Path $tarFile) { Remove-Item $tarFile }
tar -C $LocalWebPath -czf $tarFile .

# ── Step 2: Upload tarball ────────────────────────────────────
Write-Step "Uploading tarball..."
scp @sshOpts $tarFile "$($sshTarget):/tmp/web.tar.gz"

# ── Step 3: Extract tarball and fix ownership ─────────────────
Write-Step "Extracting on server..."
ssh @sshOpts $sshTarget @"
sudo mkdir -p $RemotePath
sudo tar -xzf /tmp/web.tar.gz -C $RemotePath
sudo chown -R businessapp:businessapp $RemotePath
echo DEPLOY_OK
"@ 2>&1 | ForEach-Object { if ($_ -match "DEPLOY_OK") { Write-OK "Web folder deployed" } }

# ── Step 4: Restart app ───────────────────────────────────────
Write-Step "Restarting supervisor + nginx..."
ssh @sshOpts $sshTarget @"
sudo supervisorctl restart ethiopian-business
sudo systemctl restart nginx
echo RESTART_DONE
"@ 2>&1 | ForEach-Object { if ($_ -match "RESTART_DONE") { Write-OK "App restarted" } }

Write-Host "`nDeployment complete!" -ForegroundColor Yellow