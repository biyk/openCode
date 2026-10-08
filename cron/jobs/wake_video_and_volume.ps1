# Включает тестовый ролик YouTube в CDP-браузере, снимает mute мастера и
# выставляет громкость 40% (шаг 4: -Set + -Unmute — уровень и mute в Core Audio
# независимы, без -Unmute будильник играл бы в заглушенный endpoint "тихо").
# Каждый шаг проверяет результат и пишет в stdout («вывод» шага берёт в лог
# планировщик cron) — видно, на каком этапе всё сломалось.
$ErrorActionPreference = "Continue"
$video = "y65necIJU2Y"
$url = "https://www.youtube.com/watch?v=$video"

Write-Output "[step 1] браузер: статус"
python -m lib.browser_control status
if ($LASTEXITCODE -ne 0) {
    Write-Output "[step 1] браузер не запущен - open-url запустит сам"
}

Write-Output "[step 2] открыть $url (идемпотентно)"
# Идемпотентность: будильник мог сработать дважды (ручная правка crontab
# в соседнюю минуту, рестарт процесса), а open-new ВСЕГДА создаёт вкладку —
# получаем дубли. Если вкладка с этим id уже есть — пропускаем открытие.
# Через open-url не решается: он матчит по хосту и переключается на любую
# youtube-вкладку, наш ролик мог бы не открыться.
$tabs = python -m lib.browser_control tabs 2>$null | Out-String
if ($tabs -and $tabs.Contains($video)) {
    Write-Output "[step 2] вкладка с $video уже открыта - пропускаю open-new"
} else {
    python -m lib.browser_control open-new $url
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[step 2] НЕ ОТКРЫЛСЯ: open-new вернул ошибку"
        exit 1
    }
}

# Вкладка создана != страница загрузилась и плеер играет: проверяем состояние.
# 5 попыток; eval при отсутствии вкладки ждёт её сам до 15 с, худший случай
# должен влезать в таймаут задания (см. crontab.json).
$state = "нет-данных"
for ($i = 1; $i -le 5; $i++) {
    Start-Sleep -Seconds 2
    $res = python -m lib.browser_control eval $video `
        "(function(){var v=document.querySelector('video');if(!v)return 'no-video';return v.paused?'paused':'playing'})()" `
        2>&1 | Select-Object -Last 1
    if ($res -match "не найдена") {
        # open-url переключился на другой youtube-таб или страница
        # не загрузилась — нашего ролика в браузере нет
        Write-Error "[step 3] РОЛИК НЕ ОТКРЫЛСЯ: вкладка с $video не найдена"
        exit 1
    }
    $state = "$res".Trim()
    Write-Output "[step 3.$i] состояние плеера: $state"
    if ($state -eq "paused") {
        # автоплей мог не пропустить фоновую вкладку - попробуем запустить
        python -m lib.browser_control eval $video "(function(){var v=document.querySelector('video');if(v){v.play();return 'play-called'}return 'no-video'})()" | Out-Null
    }
    if ($state -eq "playing") { break }
}
if ($state -ne "playing") {
    Write-Error "[step 3] НЕ ЗАИГРАЛ: плеер в состоянии $state"
    exit 1
}

Write-Output "[step 4] снять mute и громкость -> 40"
$vol = powershell -NoProfile -ExecutionPolicy Bypass -File bin/get_volume.ps1 -Set 40 -Unmute
Write-Output "[step 4] громкость теперь: $vol"
Write-Output "[done] все шаги выполнены"
