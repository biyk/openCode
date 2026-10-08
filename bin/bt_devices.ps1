# TOOLTIP: Список Bluetooth-устройств Windows + попытка прочитать заряд (печатает JSON)
# Диагностика: python -m lib.runtime.bluetooth
#
# Устройство = devnode BTHENUM\DEV_<MAC> (классика/EDR) или BTHLE\DEV_<MAC> (LE).
# Профили (A2DP/AVRCP/HFP/HID/SPP) собираем из соседних devnode'ов с тем же адресом.
#
# Заряд — только из того, что Windows отдаёт без WDK и WinRT:
#   1) root\wmi\BatteryStatus + BatteryFullChargedCapacity для батарейного devnode'а
#      того же контейнера (так работают HID-батареи, в т.ч. Bluetooth-мыши);
#   2) BatteryStatus, чей InstanceName начинается с id самого BT-devnode'а;
#   3) наличие GATT Battery Service {0000180F-...}: Windows его видит, но процент не отдаёт.
# Иначе percent=$null и код source (ASCII): текст объяснения печатает python-обвязка,
# потому что PS 5.1 читает файл как ANSI и ломает кириллицу внутри строковых литералов.
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

$NULL_CONTAINER = '{00000000-0000-0000-FFFF-FFFFFFFFFFFF}'

$PROFILE_NAMES = @{
    '00001101' = 'SPP'
    '0000110B' = 'A2DP'
    '0000110C' = 'A2DP-Sink'
    '0000110E' = 'AVRCP'
    '0000111E' = 'HFP'
    '00001124' = 'HID'
}

function Get-Mac([string]$InstanceId) {
    if ($InstanceId -match '\\DEV_([0-9A-Fa-f]{12})\\') { return $Matches[1].ToUpper() }
    return $null
}

function Get-AddressFromId([string]$InstanceId) {
    # адрес из ЛЮБОГО devnode'а: убираем GUID-ы в {…}, ищем ровно 12 hex
    $clean = [regex]::Replace($InstanceId, '\{[^}]*\}', '')
    $m = [regex]::Match($clean, '(?<![0-9A-Fa-f])([0-9A-Fa-f]{12})(?![0-9A-Fa-f])')
    if ($m.Success) { return $m.Groups[1].Value.ToUpper() }
    return $null
}

function Format-Mac([string]$Address) {
    $parts = @()
    for ($i = 0; $i -lt 12; $i += 2) { $parts += $Address.Substring($i, 2) }
    return ($parts -join ':')
}

function Get-ConnectionCount([string]$InstanceId) {
    $k = 'HKLM:\SYSTEM\CurrentControlSet\Enum\' + $InstanceId + '\Device Parameters'
    if (Test-Path $k) {
        $v = (Get-ItemProperty $k).ConnectionCount
        if ($null -ne $v) { return [int]$v }
    }
    return $null
}

function Get-Normalized([string]$Name) { return ($Name -replace '_\d+$', '').ToUpper() }

# --- InstanceName(норм.) -> {percent; charging} из двух разных WMI-классов ---
function Get-BatteryMap {
    $cap = @{}
    foreach ($f in (Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity)) {
        if ($f.InstanceName -and $f.FullChargedCapacity -gt 0) {
            $cap[(Get-Normalized $f.InstanceName)] = [double]$f.FullChargedCapacity
        }
    }
    $map = @{}
    foreach ($b in (Get-CimInstance -Namespace root/wmi -ClassName BatteryStatus)) {
        if (-not $b.InstanceName) { continue }
        $key = Get-Normalized $b.InstanceName
        if (-not $cap.ContainsKey($key)) { continue }
        if ($null -eq $b.RemainingCapacity) { continue }
        $pct = [int][Math]::Round(100 * [double]$b.RemainingCapacity / $cap[$key])
        if ($pct -lt 0) { $pct = 0 }
        if ($pct -gt 100) { $pct = 100 }
        $map[$b.InstanceName.ToUpper()] = @{
            percent  = $pct
            charging = [bool]$b.Charging
            runtime  = [int]$b.RemainingCapacity
        }
    }
    return $map
}

function Get-ContainerId([string]$InstanceId) {
    $raw = (Get-PnpDeviceProperty -InstanceId $InstanceId -Key DEVPKEY_Device_ContainerId).Data
    if (-not $raw) { return $null }
    $s = $raw.ToString().ToUpper()
    if ($s -eq $NULL_CONTAINER.ToUpper()) { return $null }
    return $s
}

$batteryMap = Get-BatteryMap
$all = @(Get-PnpDevice)

# --- контейнер -> заряд батарейного devnode'а того же контейнера ---
$containerBattery = @{}
foreach ($bd in @($all | Where-Object { $_.Class -eq 'Battery' })) {
    $cid = Get-ContainerId $bd.InstanceId
    if (-not $cid) { continue }
    $prefix = $bd.InstanceId.ToUpper()
    foreach ($name in $batteryMap.Keys) {
        if ($name.StartsWith($prefix)) {
            $containerBattery[$cid] = $batteryMap[$name]
            $containerBattery[$cid]['source'] = 'battery-devnode'
            break
        }
    }
}

# --- адреса, публикующие GATT Battery Service {0000180F-...} ---
$gattBattery = @{}
foreach ($d in @($all | Where-Object { $_.InstanceId -like 'BTHLEDEVICE\{0000180F-*' })) {
    $addr = Get-AddressFromId $d.InstanceId
    if ($addr) { $gattBattery[$addr] = $true }
}

# --- адрес -> профили (только регулярки: devnode'ов ~800, свойства не дёргаём) ---
$profilesByAddr = @{}
foreach ($d in $all) {
    if ($d.InstanceId -notmatch '\{(0000[0-9A-Fa-f]{4})-') { continue }
    $uuid = $Matches[1].ToUpper()
    if (-not $PROFILE_NAMES.ContainsKey($uuid)) { continue }
    $addr = Get-AddressFromId $d.InstanceId
    if (-not $addr) { continue }
    if (-not $profilesByAddr.ContainsKey($addr)) { $profilesByAddr[$addr] = @() }
    $p = $PROFILE_NAMES[$uuid]
    if ($profilesByAddr[$addr] -notcontains $p) { $profilesByAddr[$addr] += $p }
}

$devices = @()
foreach ($d in @($all | Where-Object { $_.InstanceId -match '^(BTHENUM|BTHLE)\\DEV_[0-9A-Fa-f]{12}\\' })) {
    $addr = Get-Mac $d.InstanceId
    if (-not $addr) { continue }
    $conn = Get-ConnectionCount $d.InstanceId
    $transport = if ($d.InstanceId -like 'BTHLE\*') { 'LE' } else { 'BREDR' }
    $cid = Get-ContainerId $d.InstanceId

    $batt = $null
    if ($cid -and $containerBattery.ContainsKey($cid)) {
        $batt = $containerBattery[$cid]
    }
    if (-not $batt) {
        $prefix = $d.InstanceId.ToUpper()
        foreach ($name in $batteryMap.Keys) {
            if ($name.StartsWith($prefix)) {
                $batt = $batteryMap[$name]
                $batt['source'] = 'battery-status'
                break
            }
        }
    }
    if (-not $batt) {
        $src = 'none'
        if ($gattBattery.ContainsKey($addr)) { $src = 'gatt-service-visible' }
        $batt = @{ percent = $null; charging = $null; source = $src }
    }

    $prof = @()
    if ($profilesByAddr.ContainsKey($addr)) { $prof = @($profilesByAddr[$addr]) }

    $devices += @{
        name       = $d.FriendlyName
        mac        = Format-Mac $addr
        transport  = $transport
        present    = [bool]$d.Present
        status     = '' + $d.Status
        connected  = ($null -ne $conn -and $conn -gt 0)
        conn_count = $conn
        profiles   = $prof
        instance   = $d.InstanceId
        battery    = $batt
    }
}

$radios = @($all | Where-Object {
    $_.Class -eq 'Bluetooth' -and $_.InstanceId -like 'USB\*'
} | ForEach-Object { @{ name = $_.FriendlyName; status = '' + $_.Status } })

$out = @{
    os_build      = (Get-CimInstance -ClassName Win32_OperatingSystem).BuildNumber
    battery_total = $batteryMap.Count
    radios        = $radios
    devices       = $devices
}
ConvertTo-Json -InputObject $out -Depth 6
