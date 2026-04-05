# setup_autostart.ps1
# Compatible with PowerShell 5+

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$cfgPath = Join-Path $dir "bg_config.json"

try {

# ── Read config ───────────────────────────────────────────────────────────────
if (!(Test-Path $cfgPath)) {
    Write-Host "ERROR: bg_config.json not found!" -ForegroundColor Red
    Write-Host "Please run start.bat and click Apply first." -ForegroundColor Yellow
    throw "Config not found"
}

$cfg = Get-Content $cfgPath | ConvertFrom-Json
$dll = $cfg.dll_path

if (!$dll -or !(Test-Path $dll)) {
    Write-Host "ERROR: DLL path not set or file missing!" -ForegroundColor Red
    Write-Host "Please run start.bat and click Apply first." -ForegroundColor Yellow
    throw "DLL not found"
}

Write-Host "Found DLL: $dll" -ForegroundColor Cyan

# ── Write VBS launcher using here-string (no quote escaping issues) ───────────
$vbs = Join-Path $dir "launch_bg_silent.vbs"
$vbsContent = @"
Set oShell = CreateObject("Shell.Application")
oShell.ShellExecute "regsvr32", "/s ""$dll""", "", "runas", 0
"@
[System.IO.File]::WriteAllText($vbs, $vbsContent, [System.Text.Encoding]::ASCII)
Write-Host "Created VBS: $vbs" -ForegroundColor Cyan

# ── Task 1: DLL registration ──────────────────────────────────────────────────
schtasks /delete /tn "ExplorerBgTool" /f 2>$null

$action1   = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbs`""
$trigger1  = New-ScheduledTaskTrigger -AtLogOn
$settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask `
    -TaskName "ExplorerBgTool" `
    -Action $action1 `
    -Trigger $trigger1 `
    -Settings $settings1 `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "OK: DLL auto-start registered" -ForegroundColor Green

# ── Task 2: Wallpaper watcher ─────────────────────────────────────────────────
$watcherScript = Join-Path $dir "wallpaper_watcher.py"

if (Test-Path $watcherScript) {
    # Find pythonw.exe
    $pythonw = $null
    $pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCmd) {
        $candidate = Join-Path (Split-Path $pythonCmd.Source) "pythonw.exe"
        if (Test-Path $candidate) { $pythonw = $candidate }
    }
    if (!$pythonw) {
        $locations = @(
            "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python310\pythonw.exe",
            "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
            "C:\Python311\pythonw.exe",
            "C:\Python310\pythonw.exe"
        )
        foreach ($p in $locations) {
            if (Test-Path $p) { $pythonw = $p; break }
        }
    }

    if ($pythonw) {
        schtasks /delete /tn "ExplorerBgWatcher" /f 2>$null
        $action2   = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$watcherScript`""
        $trigger2  = New-ScheduledTaskTrigger -AtLogOn
        $settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit "00:00:00"
        Register-ScheduledTask `
            -TaskName "ExplorerBgWatcher" `
            -Action $action2 `
            -Trigger $trigger2 `
            -Settings $settings2 `
            -RunLevel Highest `
            -Force | Out-Null
        Write-Host "OK: Wallpaper watcher registered ($pythonw)" -ForegroundColor Green
    } else {
        Write-Host "WARNING: pythonw.exe not found - watcher will not auto-start on boot" -ForegroundColor Yellow
        Write-Host "         Watcher still works when you run start.bat manually" -ForegroundColor Yellow
    }
} else {
    Write-Host "WARNING: wallpaper_watcher.py not found - skipping watcher task" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done! Setup complete." -ForegroundColor Green
Write-Host "  - Explorer background applies on every login" -ForegroundColor Cyan
Write-Host "  - Wallpaper watcher auto-syncs Spotlight changes if wallpaper mode is on" -ForegroundColor Cyan
Write-Host ""
Write-Host "To remove auto-start, run REMOVE_AUTOSTART.bat"
Write-Host ""

} catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
}

Write-Host "Press any key to close..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
