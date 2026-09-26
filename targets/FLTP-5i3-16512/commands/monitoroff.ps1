# TOOLTIP: PowerShell-скрипт гасит монитор: шлёт HWND_BROADCAST (0xFFFF) WM_SYSCOMMAND (0x0112) с SC_MONITORPOWER (0xF170) и lParam=2 (off) через user32 SendMessageTimeout — экран гаснет, будит любой ввод (мышь/клавиатура); блокировки и сна ПК нет.
$s = 'using System;using System.Runtime.InteropServices;public class M{[DllImport("user32.dll",CharSet=CharSet.Auto)]public static extern IntPtr SendMessageTimeout(IntPtr hWnd,uint Msg,IntPtr wParam,IntPtr lParam,uint fuFlags,uint uTimeout,out IntPtr lpdwResult);public static void Off(){IntPtr r;SendMessageTimeout((IntPtr)0xffff,0x0112,(IntPtr)0xF170,(IntPtr)2,2,10000,out r);}}'
Add-Type -TypeDefinition $s -ErrorAction Stop
[M]::Off()
