param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,
    [string]$SSHKey = "$HOME\.ssh\id_rsa",
    [string]$LocalWebPath = "C:\Users\info\Documents\GitHub\accounting\web",
    [string]$RemotePath = "/opt/ethiopian-business/web"
)

function Write-OK   { param($m) Write-Host "  [OK]   $m" -ForegroundColor Green }
function Write-Step { param($m) Write-Host "`n=> $m" -ForegroundColor Cyan }

$sshTarget = "ubuntu@$ServerIP"
$sshOpts   = @('-o','StrictHostKeyChecking=no','-o','ConnectTimeout=10','-i',$SSHKey)

# Step 1: Create tar of web folder
Write-Step "Creating tarball..."
$tarFile = Join-Path $env:TEMP "web.tar.gz"
if (Test-Path $tarFile) { Remove-Item $tarFile }

tar -C $LocalWebPath -czf $tarFile .

# Step 2: Upload tarball
Write-Step "Uploading tarball..."
scp @sshOpts $tarFile "${sshTarget}:/tmp/web.tar.gz"

# Step 3: Extract tarball and fix ownership
Write-Step "Extracting on server..."
ssh @sshOpts $sshTarget @"
sudo mkdir -p $RemotePath
sudo tar -xzf /tmp/web.tar.gz -C $RemotePath
sudo chown -R businessapp:businessapp $RemotePath
echo DEPLOY_OK
"@ 2>&1 | ForEach-Object {
    if ($_ -match "DEPLOY_OK") { Write-OK "Web folder deployed" }
}

# Step 4: Restart app
Write-Step "Restarting supervisor + nginx..."
ssh @sshOpts $sshTarget @"
sudo supervisorctl restart ethiopian-business
sudo systemctl restart nginx
echo RESTART_DONE
"@ 2>&1 | ForEach-Object {
    if ($_ -match "RESTART_DONE") { Write-OK "App restarted" }
}

Write-Host "`nDeployment complete!" -ForegroundColor Yellow