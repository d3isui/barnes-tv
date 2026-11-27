<#
  Opens Windows Firewall for Barnes Television Broadcasting System so other devices (Chromecasts, TVs, phones,
  Jellyfin on another PC) can reach it. Run from an *administrator* PowerShell in the folder:
      powershell -ExecutionPolicy Bypass -File scripts\open-firewall.ps1
  -AnyAddress also accepts devices outside your local network (VPNs); -Remove takes the rules away again.
  (install-windows-startup.ps1 does this too.)
#>
param([int]$Port = 8420, [switch]$AnyAddress, [switch]$Remove, [switch]$Public)   # -Public: old option, no longer needed
$ErrorActionPreference = "Stop"
$Name = "Barnes TV Broadcast"
$Root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "firewall-common.ps1")
if ($Remove) {
    foreach ($n in @($Name, "$Name (Chromecast discovery)", "$Name (Python)", "Jellyfin Broadcast", "Jellyfin Broadcast (Chromecast discovery)")) {
        Remove-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue
    }
    Write-Host "Firewall rules removed."
    exit 0
}
Set-BarnesFirewall $Root $Port ([bool]$AnyAddress)
