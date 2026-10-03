# lib/voice_cmd/knowledge_review_ui_log.py
"""Попап журнала распознавания: ссылка «логи» на вкладке «Сервер».

Само содержимое — след последнего прогона «распознать все» (строки фаз,
оценки, причины пропусков), который собирает knowledge_review_bulk и отдаёт
`GET /api/recognize_log`. Живёт в памяти доски, на диск не пишется.

Фрагмент подключается к странице так: `page()` вставляет POPUP перед
</body> — отдельный файл нужен потому, что knowledge_review_ui ровно в
потолке 200 строк (scripts/check_lengths).
"""

from __future__ import annotations

from lib.voice_cmd.knowledge_review_ui import PAGE

# Кнопка открывается по клику и закрывается по ✕ или Esc; текст — <pre>,
# чтобы табуляция и выравнивание колонок в логе сохранились.
POPUP = """
<style>
 #logm{position:fixed;inset:.5rem;z-index:9;background:#181820;
  border:1px solid #555;padding:.6rem;display:none;flex-direction:column}
 #logm.on{display:flex}
 #logt{flex:1;overflow:auto;margin:.4rem 0 0;padding:.5rem;background:#1e1e28;
  border:1px solid #444;font:.8rem/1.35 ui-monospace,Consolas,monospace;
  white-space:pre}
</style>
<div id=logm><div><button id=logc>✕ закрыть</button>
 <span class=note id=logn></span></div><pre id=logt></pre></div>
<script>
async function showLog(){const m=document.getElementById("logm");
 m.classList.add("on");const t=document.getElementById("logt"),
 n=document.getElementById("logn");n.textContent="читаю…";
 try{const j=await (await fetch("/api/recognize_log")).json();
  t.textContent=j.log||"прогонов ещё не было: нажми «распознать все»";
  n.textContent=`${j.running?"прогон идёт · ":""}${j.done||0}/${j.total||0} фраз`}
 catch(e){n.textContent="журнал недоступен";t.textContent=String(e)}}
document.addEventListener("click",ev=>{const b=ev.target;
 if(b.id=="logb"){showLog();return}
 if(b.id=="logc")document.getElementById("logm").classList.remove("on")});
document.addEventListener("keydown",ev=>{if(ev.key=="Escape")
 document.getElementById("logm").classList.remove("on")});
</script>
"""


def page() -> str:
    """Страница доски с подключённым попапом журнала распознавания."""
    return PAGE.replace("</body>", POPUP + "</body>")
