param([int]$StepPercent = 6)
$presses = [System.Math]::Max(1, [System.Math]::Round($StepPercent / 2))
$s = 'using System;using System.Runtime.InteropServices;public class V{[DllImport("user32.dll")]public static extern void keybd_event(byte bVk,byte bScan,uint dwFlags,IntPtr dwExtraInfo);public static void Up(int count){for(int i=0;i<count;i++){keybd_event(0xAF,0,0,IntPtr.Zero);keybd_event(0xAF,0,2,IntPtr.Zero);}}}'
Add-Type -TypeDefinition $s -ErrorAction Stop
[V]::Up($presses)