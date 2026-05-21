#!/usr/bin/env pwsh
# GitHub 自动同步脚本

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$ipFile = "ip.txt"
$commitMsg = "Update IP list - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

if (-not (Test-Path $ipFile)) {
    Write-Host "[WARN] File $ipFile not found, skip push" -ForegroundColor Yellow
    exit 0
}

Write-Host "Checking Git status..." -ForegroundColor Cyan
$status = git status --porcelain $ipFile 2>&1

if ([string]::IsNullOrWhiteSpace($status)) {
    Write-Host "[OK] No changes to commit for $ipFile" -ForegroundColor Green
    exit 0
}

Write-Host "Adding changes..." -ForegroundColor Cyan
$addOutput = git add $ipFile 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Git add failed: $addOutput" -ForegroundColor Red
    exit 1
}

Write-Host "Committing changes..." -ForegroundColor Cyan
$commitOutput = git commit -m $commitMsg 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($commitOutput -match "nothing to commit") {
        Write-Host "[OK] Nothing to commit" -ForegroundColor Green
        exit 0
    }
    Write-Host "[ERROR] Git commit failed: $commitOutput" -ForegroundColor Red
    exit 1
}

Write-Host "Pushing to remote..." -ForegroundColor Cyan
$pushOutput = git push origin HEAD 2>&1
$pushExitCode = $LASTEXITCODE

if ($pushExitCode -eq 0) {
    Write-Host "[OK] Successfully pushed to GitHub" -ForegroundColor Green
    Write-Host $pushOutput
    exit 0
} else {
    if ($pushOutput -match "Everything up-to-date") {
        Write-Host "[OK] Repository is already up-to-date" -ForegroundColor Green
        exit 0
    }
    Write-Host "[ERROR] Push failed (exit code: $pushExitCode)" -ForegroundColor Red
    Write-Host "Output: $pushOutput" -ForegroundColor Yellow
    exit 1
}
