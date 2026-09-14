# Определяет состояние медиа через Windows.Media.Control
# (GlobalSystemMediaTransportControlsSessionManager).
# По умолчанию: "true", если хоть одна сессия в Playing.
# С ключом -AnySession: "true", если есть хоть одна сессия
# (Playing/Paused/Stopped — главное, что есть чем управлять).
# Выводит "true" или "false".
param([switch]$AnySession)
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $managerMethod = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager].GetMethod('RequestAsync')
    $task = $asTaskGeneric.MakeGenericMethod([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]).Invoke($null, @($managerMethod.Invoke($null, @())))
    $task.Wait()
    $manager = $task.Result
    $playing = $false
    foreach ($session in $manager.GetSessions()) {
        try {
            # PlaybackStatus имеет тип GlobalSystemMediaTransportControlsSessionPlaybackStatus
            # (НЕ Windows.Media.MediaPlaybackStatus!) — сравниваем строкой.
            $status = "$($session.GetPlaybackInfo().PlaybackStatus)"
            if ($AnySession -or $status -eq "Playing") {
                $playing = $true
                break
            }
        } catch { }
    }
    if ($playing) { 'true' } else { 'false' }
} catch {
    'false'
}