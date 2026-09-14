# Стоп с фолбэком: шлём Media Stop (0xB2); если через пару секунд
# медиа всё ещё играет (например, YouTube игнорирует Stop) —
# жмём Play/Pause (0xB3), чтобы поставить на паузу.
$s = 'using System;using System.Runtime.InteropServices;public class K{[DllImport("user32.dll")]public static extern void keybd_event(byte bVk,byte bScan,uint dwFlags,IntPtr dwExtraInfo);public static void k(byte v){keybd_event(v,0,0,IntPtr.Zero);keybd_event(v,0,2,IntPtr.Zero);}}'
Add-Type -TypeDefinition $s -ErrorAction Stop
[K]::k(0xB2)
Start-Sleep -Seconds 2
$root = Split-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) -Parent
$state = & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "bin/media_state.ps1") 2>$null
if ("$state".Trim() -eq "true") {
    [K]::k(0xB3)
}
