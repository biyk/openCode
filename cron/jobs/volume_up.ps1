# Поднимает громкость на один шаг (клавиша volume up, как в команде «громче»).
# Шаг проверяется фактическим уровнем до и после: без изменения = клавиша не
# дошла (звук выключен/другое устройство/сессия), вывод берёт в лог cron.
$before = powershell -NoProfile -ExecutionPolicy Bypass -File bin/get_volume.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "targets/FLTP-5i3-16512/commands/volumeup.ps1" 6
Start-Sleep -Milliseconds 300
$after = powershell -NoProfile -ExecutionPolicy Bypass -File bin/get_volume.ps1
Write-Output "volume: $before -> $after"
if ($before -eq $after) {
    Write-Error "НЕ ПОДНЯЛАСЬ: уровень $before не изменился (клавиша не дошла?)"
    exit 1
}
