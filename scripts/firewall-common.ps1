<#
  Shared by install-windows-startup.ps1 and open-firewall.ps1: lets other devices on your network reach
  Barnes Television Broadcasting System through Windows Firewall.

  Why it's more than one rule:
  * A venv's python.exe / pythonw.exe is only a launcher: the program that actually listens is the Python it was
    made from (e.g. C:\Users\you\AppData\Local\Programs\Python\Python312\pythonw.exe). Program rules must name that.
  * When Windows asks "allow Python on private/public networks?", every box you leave unticked becomes a BLOCK rule,
    and block rules beat every allow rule. Those are removed here (only for this Python).
  * If Windows thinks your home network is "Public", rules for Private networks don't apply. The rules below work on
    any network type but only accept devices on your own local network (unless -AnyAddress).
#>

function Get-BarnesPrograms([string]$Root) {
    $venv = Join-Path $Root ".venv\Scripts"
    $list = @((Join-Path $venv "python.exe"), (Join-Path $venv "pythonw.exe"))
    $vpy = Join-Path $venv "python.exe"
    if (Test-Path $vpy) {
        try {
            $base = (& $vpy -c "import sys; print(getattr(sys, '_base_executable', '') or sys.executable)" 2>$null | Select-Object -First 1)
            if ($base) {
                $dir = Split-Path -Parent ($base.Trim())
                $list += (Join-Path $dir "python.exe"), (Join-Path $dir "pythonw.exe")
            }
        } catch { }
    }
    return $list | Where-Object { Test-Path $_ } | Select-Object -Unique
}

function Set-BarnesFirewall([string]$Root, [int]$Port, [bool]$AnyAddress = $false) {
    $Name = "Barnes TV Broadcast"
    $remote = if ($AnyAddress) { "Any" } else { "LocalSubnet" }
    foreach ($n in @($Name, "$Name (Chromecast discovery)", "$Name (Python)", "Jellyfin Broadcast", "Jellyfin Broadcast (Chromecast discovery)")) {
        Remove-NetFirewallRule -DisplayName $n -ErrorAction SilentlyContinue
    }
    $progs = @(Get-BarnesPrograms $Root)
    Write-Host "Python programs used by Barnes TV:"
    $progs | ForEach-Object { Write-Host "   $_" }

    # 1. block rules for this Python (left over from a Windows Firewall prompt) beat every allow rule: remove them
    Write-Host "Looking for Windows Firewall rules that block Python (this can take a few seconds)..."
    $removed = 0
    $filters = Get-NetFirewallApplicationFilter -ErrorAction SilentlyContinue | Where-Object {
        $p = [Environment]::ExpandEnvironmentVariables([string]$_.Program)
        $progs -contains $p
    }
    foreach ($f in $filters) {
        $rule = $f | Get-NetFirewallRule -ErrorAction SilentlyContinue
        if ($rule -and $rule.Direction -eq "Inbound" -and $rule.Action -eq "Block") {
            Write-Host "   removing block rule: $($rule.DisplayName) ($($rule.Profile))" -ForegroundColor Yellow
            Remove-NetFirewallRule -Name $rule.Name
            $removed++
        }
    }
    if ($removed -eq 0) { Write-Host "   none found" }

    # 2. allow the web port (any program, any network type, devices on the local network)
    New-NetFirewallRule -DisplayName $Name -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow `
        -Profile Any -RemoteAddress $remote | Out-Null
    # 3. Chromecasts answering the app's "who's out there?" (mDNS, UDP 5353), for this Python only
    foreach ($p in $progs) {
        New-NetFirewallRule -DisplayName "$Name (Chromecast discovery)" -Direction Inbound -Protocol UDP -LocalPort 5353 `
            -Program $p -Action Allow -Profile Any -RemoteAddress $remote | Out-Null
    }
    Write-Host "Opened TCP port $Port and Chromecast discovery for devices on " -NoNewline
    Write-Host $(if ($AnyAddress) { "any network." } else { "your local network (any network type)." })

    foreach ($net in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
        Write-Host "Network '$($net.Name)' is set to: $($net.NetworkCategory)"
    }
    $ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -ExpandProperty IPAddress
    foreach ($ip in $ips) { Write-Host "From other devices, try:  http://${ip}:$Port/" -ForegroundColor Green }
}

function Show-BarnesStatus([string]$Root, [int]$Port, [string]$TaskName) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) { Write-Host "Startup task: $($t.State)" } else { Write-Host "Startup task: not installed" }
    $l = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($l) {
        $proc = Get-Process -Id $l.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "Port ${Port}: listening on $($l.LocalAddress) by $($proc.Path)"
    } else {
        Write-Host "Port ${Port}: nothing is listening (the server isn't running)" -ForegroundColor Yellow
    }
    Get-NetFirewallRule -DisplayName "Barnes TV Broadcast*" -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host "Firewall rule: $($_.DisplayName) [$($_.Action), $($_.Profile), enabled=$($_.Enabled)]" }
    foreach ($net in @(Get-NetConnectionProfile -ErrorAction SilentlyContinue)) {
        Write-Host "Network '$($net.Name)' is set to: $($net.NetworkCategory)"
    }
}
