# setup_autostart.ps1
# Registers ExplorerBgTool to auto-apply on every Windows login.

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgPath = Join-Path $dir "bg_config.json"

# Read DLL path from saved config
if (!(Test-Path $cfgPath)) {
    Write-Host "ERROR: bg_config.json not found!" -ForegroundColor Red
    Write-Host "Please run the app (start.bat) and click Apply first." -ForegroundColor Yellow
    pause; exit
}

$cfg = Get-Content $cfgPath | ConvertFrom-Json
$dll = $cfg.dll_path

if (!$dll -or !(Test-Path $dll)) {
    Write-Host "ERROR: DLL path not set or file missing!" -ForegroundColor Red
    Write-Host "Please run the app (start.bat) and click Apply first." -ForegroundColor Yellow
    pause; exit
}

Write-Host "Found DLL: $dll" -ForegroundColor Cyan

# Write a silent VBS launcher (no window flash)
$vbs = Join-Path $dir "launch_bg_silent.vbs"
$vbsContent = @"
Set oShell = CreateObject("Shell.Application")
oShell.ShellExecute "regsvr32", "/s ""$dll""", "", "runas", 0
"@
Set-Content -Path $vbs -Value $vbsContent -Encoding ASCII
Write-Host "Created launcher: $vbs" -ForegroundColor Cyan

# Remove old task if it exists
schtasks /delete /tn "ExplorerBgTool" /f 2>$null

# Register new scheduled task
$action   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask `
    -TaskName "ExplorerBgTool" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host ""
Write-Host "Done! Explorer background will now auto-apply on every login." -ForegroundColor Green
Write-Host "To remove, run REMOVE_AUTOSTART.bat"
Write-Host ""
pause
