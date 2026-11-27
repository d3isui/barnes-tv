<#
  Runs Barnes Television Broadcasting System automatically when Windows starts (no console window) and opens
  Windows Firewall so your other devices can reach it. Run from an *administrator* PowerShell in the folder:
      powershell -ExecutionPolicy Bypass -File scripts\install-windows-startup.ps1
  Options:
      -Check        show what's running and how the firewall is set up, change nothing
      -Uninstall    remove the startup task and the firewall rules
      -AnyAddress   also accept connections from outside your local network (e.g. a VPN like Tailscale)
      -Port 8420    a different port
#>
param([int]$Port = 8420, [switch]$Uninstall, [switch]$Check, [switch]$AnyAddress)
$ErrorActionPreference = "Stop"
$Name = "Barnes TV Broadcast"
$OldName = "Jellyfin Broadcast"   # tasks created by earlier versions
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "firewall-common.ps1")

if ($Check) { Show-BarnesStatus $Root $Port $Name; exit 0 }

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    foreach ($n in @($Name, "$Name (Chromecast discovery)", "$Name (Python)")) { Remove-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue }
    Write-Host "Removed the startup task and firewall rules."
    exit 0
}

$Py = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Setting up Python environment first..."
    $launcher = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
    & $launcher -m venv (Join-Path $Root ".venv")
    & (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -q -r (Join-Path $Root "requirements.txt")
}

Unregister-ScheduledTask -TaskName $OldName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $Py -Argument "`"$Root\broadcast.py`" --port $Port" -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null

Set-BarnesFirewall $Root $Port ([bool]$AnyAddress)

Start-ScheduledTask -TaskName $Name
Start-Sleep -Seconds 4
Write-Host ""
Show-BarnesStatus $Root $Port $Name
Write-Host ""
Write-Host "Installed. Barnes Television Broadcasting System starts with Windows (before anyone signs in)."
Write-Host "Close any start.bat window: only one copy can use port $Port."
Write-Host "Note: it runs as the SYSTEM account. If you use 'direct' media access with network shares, use UNC paths (\\server\share)."
