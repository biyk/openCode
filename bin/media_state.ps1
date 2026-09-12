# Определяет, воспроизводится ли в данный момент медиа (музыка/видео)
# через Windows.Media.Control (GlobalSystemMediaTransportControlsSessionManager).
# Выводит "true" или "false".
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $managerMethod = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager].GetMethod('RequestAsync')
    $task = $asTaskGeneric.MakeGenericMethod([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]).Invoke($null, @($managerMethod.Invoke($null, @())))
    $task.Wait()
    $manager = $task.Result
    $session = $manager.GetCurrentSession()
    if ($null -eq $session) { 'false'; exit }
    $status = $session.GetPlaybackInfo().PlaybackStatus
    if ($status -eq [Windows.Media.MediaPlaybackStatus]::Playing) { 'true' } else { 'false' }
} catch {
    'false'
}