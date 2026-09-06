param(
    [Parameter(Mandatory=$true)][string]$TextFile,
    [Parameter(Mandatory=$true)][string]$OutFile
)
Add-Type -AssemblyName System.Speech
$text = Get-Content -LiteralPath $TextFile -Raw -Encoding UTF8
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $synth.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Name -like "*Irina*" -or $_.VoiceInfo.Culture.Name -eq "ru-RU" } |
    Select-Object -First 1
if ($voice) {
    $synth.SelectVoice($voice.VoiceInfo.Name)
}
$synth.SetOutputToWaveFile($OutFile)
$synth.Speak($text)
$synth.SetOutputToNull()
$synth.Dispose()