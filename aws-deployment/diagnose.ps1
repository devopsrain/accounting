#!/usr/bin/env pwsh
param(
    [ValidateSet('All','Health','Logs','Diagnose','Fix','Watch')]
    [string]$Action = 'All',
    [string]$ServerIP,
    [string]$Region = 'af-south-1',
    [string]$SSHKey = "$HOME\.ssh\id_rsa",
    [int]$WatchInterval = 30
)

# --- Colours ---
function Write-OK      { param($m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Warn    { param($m) Write-Host "  [WARN]  $m" -ForegroundColor Yellow }
function Write-Fail    { param($m) Write-Host "  [FAIL]  $m" -ForegroundColor Red }
function Write-Info    { param($m) Write-Host "  [INFO]  $m" -ForegroundColor Cyan }
function Write-Section { param($m) Write-Host "`n═══ $m ═══" -ForegroundColor Magenta }

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir    = Join-Path $PSScriptRoot "diagnostic_logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

$findings = [System.Collections.Generic.List[string]]::new()
function Add-Finding {
    param([string]$Severity, [string]$Component, [string]$Message, [string]$Suggestion)
    $findings.Add("[$Severity] $Component - $Message | Fix: $Suggestion")
}

# --- Auto-detect IP ---
if (-not $ServerIP) {
    Write-Info "Attempting to detect IP from Terraform..."
    try {
        $ServerIP = terraform output -raw web_server_ip 2>$null
    } catch { }
}

if (-not $ServerIP -or $ServerIP -match "No outputs") {
    Write-Fail "Could not find Server IP. Please provide -ServerIP 1.2.3.4"
    exit 1
}

# --- SSH Helper ---
function Invoke-SSH {
    param([string]$Command, [int]$Timeout = 10)
    # Using -q for quiet and -o to ignore known hosts issues
    $result = ssh -i $SSHKey -o StrictHostKeyChecking=no -o ConnectTimeout=$Timeout -o BatchMode=yes "ubuntu@$ServerIP" $Command 2>&1
    return ($result -join "`n")
}

# --- Health Check Functions ---
function Test-SSHConnectivity {
    Write-Section "CONNECTIVITY CHECK"
    Write-Info "Checking Port 22 on $ServerIP..."
    $t = Test-NetConnection -ComputerName $ServerIP -Port 22 -WarningAction SilentlyContinue
    if ($t.TcpTestSucceeded) {
        Write-OK "Port 22 is OPEN"
        $out = Invoke-SSH "echo OK"
        if ($out -match "OK") { Write-OK "SSH Login Successful"; return $true }
    }
    Write-Fail "SSH Connection Failed. Is your IP whitelisted in AWS Security Groups?"
    Add-Finding "CRITICAL" "Network" "SSH Timeout" "Go to AWS Console and open Port 22 for your IP."
    return $false
}

function Test-NginxHealth {
    Write-Section "NGINX STATUS"
    $status = Invoke-SSH "systemctl is-active nginx"
    if ($status.Trim() -eq "active") { Write-OK "Nginx is running" }
    else { 
        Write-Fail "Nginx is DOWN" 
        Add-Finding "CRITICAL" "Nginx" "Service stopped" "Run: sudo systemctl restart nginx"
    }
}

function Test-SupervisorHealth {
    Write-Section "APP PROCESS (SUPERVISOR)"
    $status = Invoke-SSH "sudo supervisorctl status ethiopian-business"
    Write-Info "Status: $status"
    if ($status -match "RUNNING") { Write-OK "App is RUNNING" }
    else {
        Write-Fail "App is NOT RUNNING"
        Add-Finding "CRITICAL" "App" "Supervisor status not RUNNING" "Check /var/log/ethiopian-business.log"
    }
}

function Test-DiskSpace {
    Write-Section "SYSTEM RESOURCES"
    $df = Invoke-SSH "df -h / | tail -1"
    if ($df -match "(\d+)%") {
        $usage = [int]$Matches[1]
        if ($usage -gt 90) { Write-Fail "Disk at $usage%"; Add-Finding "WARN" "Disk" "Space low" "Clean logs" }
        else { Write-OK "Disk Space: $usage%" }
    }
}

# --- MAIN LOGIC ---
Write-Host "`nStarting Diagnostics for $ServerIP..." -ForegroundColor Cyan

if (-not (Test-SSHConnectivity)) {
    Write-Fail "Aborting diagnostics: No connection."
    exit 1
}

switch ($Action) {
    "Health" {
        Test-NginxHealth
        Test-SupervisorHealth
        Test-DiskSpace
    }
    "Logs" {
        Write-Section "COLLECTING LOGS"
        $errLog = Invoke-SSH "sudo tail -n 50 /var/log/ethiopian-business-error.log"
        $outPath = Join-Path $logDir "error_log_$timestamp.txt"
        $errLog | Out-File $outPath
        Write-OK "Last 50 lines of error log saved to $outPath"
        Write-Info "--- LOG PREVIEW ---"
        Write-Host $errLog -ForegroundColor Gray
    }
    "Fix" {
        Write-Section "RUNNING AUTO-FIX"
        Write-Info "Restarting supervisor..."
        Invoke-SSH "sudo supervisorctl restart ethiopian-business" | Out-Null
        Write-OK "Restart command sent."
    }
    "All" {
        Test-NginxHealth
        Test-SupervisorHealth
        Test-DiskSpace
        # Collect logs automatically in 'All' mode
        $logs = Invoke-SSH "sudo tail -n 20 /var/log/ethiopian-business-error.log"
        Write-Info "Recent Errors:`n$logs"
    }
}

Write-Section "DIAGNOSIS COMPLETE"
if ($findings.Count -gt 0) {
    Write-Warn "Action Items Found:"
    $findings | ForEach-Object { Write-Host " - $_" -ForegroundColor Yellow }
} else {
    Write-OK "No issues detected via SSH."
}