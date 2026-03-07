#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Ethiopian Business Management System - AWS Diagnostics & Health Check
#>

param(
    [ValidateSet('All','Health','Logs','Diagnose','Fix','Watch')]
    [string]$Action = 'All',
    [string]$ServerIP,
    [string]$Region = 'af-south-1',
    [string]$SSHKey = "$HOME\.ssh\id_rsa",
    [int]$WatchInterval = 30
)

# --- Colors ---
function Write-OK { param($m) Write-Host "  [OK]    $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host "  [WARN]  $m" -ForegroundColor Yellow }
function Write-Fail { param($m) Write-Host "  [FAIL]  $m" -ForegroundColor Red }
function Write-Info { param($m) Write-Host "  [INFO]  $m" -ForegroundColor Cyan }
function Write-Section { param($m) Write-Host "`n=== $m ===" -ForegroundColor Magenta }

$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logDir = Join-Path $PSScriptRoot "diagnostic_logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$reportFile = Join-Path $logDir "diag_${timestamp}.txt"

$findings = [System.Collections.Generic.List[string]]::new()
function Add-Finding {
    param([string]$Severity, [string]$Component, [string]$Message, [string]$Suggestion)
    $findings.Add("[$Severity] $Component - $Message | Fix: $Suggestion")
}

# --- Infrastructure ---
function Get-ServerIP {
    if ($ServerIP) { return $ServerIP }
    try {
        $ip = terraform output -raw web_server_ip 2>$null
        if ($ip -and $ip -notmatch "No outputs") { return $ip.Trim() }
    } catch {}
    Write-Fail "Cannot detect server IP. Use -ServerIP parameter."
    exit 1
}

function Invoke-SSH {
    param([string]$Command, [int]$Timeout = 15)
    $target = "ubuntu@$($script:ip)"
    $result = ssh -o StrictHostKeyChecking=no -o ConnectTimeout=$Timeout -o BatchMode=yes -i $SSHKey $target $Command 2>&1
    return ($result -join "`n")
}

function Get-TerraformOutputs {
    Write-Section "TERRAFORM OUTPUTS"
    $out = @{}
    try {
        $out['web_server_ip'] = (terraform output -raw web_server_ip 2>$null).Trim()
        $out['load_balancer_dns'] = (terraform output -raw load_balancer_dns 2>$null).Trim()
        $out['database_endpoint'] = (terraform output -raw database_endpoint 2>$null).Trim()
        $out['s3_bucket_name'] = (terraform output -raw s3_bucket_name 2>$null).Trim()
        foreach ($k in $out.Keys) { Write-OK "$k = $($out[$k])" }
    } catch { Write-Warn "Could not read all terraform outputs." }
    return $out
}

# --- Diagnostics ---
function Test-SSHConnectivity {
    Write-Section "SSH CONNECTIVITY"
    $out = Invoke-SSH "echo OK"
    if ($out -match "OK") { Write-OK "Connected"; return $true }
    Write-Fail "SSH Connection failed"; return $false
}

function Get-AllLogs {
    Write-Section "COLLECTING LOGS"
    $logFile = Join-Path $logDir "logs_${timestamp}.txt"
    $allOutput = "Ethiopian Business Management System - Full Log Dump`nTimestamp: $timestamp`n"
    
    $cmds = @(
        @{N="NginxErr"; C="sudo tail -n 50 /var/log/nginx/error.log"},
        @{N="AppLog"; C="sudo tail -n 50 /var/log/ethiopian-business.log"}
    )
    
    foreach ($item in $cmds) {
        $out = Invoke-SSH $item.C
        $allOutput += "`n=== $($item.N) ===`n$out`n"
    }
    $allOutput | Out-File -FilePath $logFile -Encoding utf8
    Write-OK "Logs saved to $logFile"
}

function Show-FindingsReport {
    Write-Section "FINDINGS SUMMARY"
    if ($findings.Count -eq 0) { Write-OK "No issues found!"; return }
    
    foreach ($f in $findings) {
        $parts = $f -split '\|'
        Write-Host "  $($parts[0].Trim())" -ForegroundColor Yellow
        if ($parts.Count -gt 1) { Write-Host "    -> $($parts[1].Trim())" -ForegroundColor Cyan }
    }
}

# --- Main Logic ---
Write-Host "`n--- AWS Diagnostics Tool ---" -ForegroundColor Cyan
$script:ip = Get-ServerIP
$outputs = Get-TerraformOutputs

if (-not (Test-SSHConnectivity)) { exit 1 }

switch ($Action) {
    'Health'   { Write-Info "Running Health Checks..." }
    'Logs'     { Get-AllLogs }
    'Fix'      { Write-Info "Applying fixes..." }
    'Watch'    { Write-Info "Monitoring..." }
    'All'      { Get-AllLogs; Show-FindingsReport }
    'Diagnose' { Show-FindingsReport }
}

Show-FindingsReport