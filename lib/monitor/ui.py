# lib/monitor/ui.py
"""HTML-страница монитора (тёмная, автообновление раз в 2с через fetch).

Одна таблица: цветной кружок + название сервиса + состояние + подробности.
Зелёный — работает, жёлтый — спит/ждёт, красный — выключен/ошибка. Раздача —
в dashboard.py (stdlib http.server), стиль как у доски знаний.
"""

PAGE = """<!doctype html><html lang=ru><head><meta charset=utf-8>
<title>Монитор сервисов</title><style>
 body{background:#15151c;color:#e6e6ee;font:14px/1.5 system-ui,sans-serif;
  margin:0;padding:1rem}
 h1{font-size:1.1rem;font-weight:600;margin:.2rem 0 1rem}
 #note{color:#8888aa;font-size:.8rem}
 table{width:100%;border-collapse:collapse}
 td{padding:.4rem .5rem;border-bottom:1px solid #26262f;vertical-align:top}
 .dot{width:12px;height:12px;border-radius:50%;display:inline-block}
 .g{background:#3fb950}.y{background:#d29922}.r{background:#f85149}
 .name{font-weight:600}.det{color:#9a9ab0;font-size:.85rem}
 .st{font-size:.85rem}
</style></head><body>
<h1>Монитор сервисов</h1>
<div id=note>читаю…</div>
<table><tbody id=tb></tbody></table>
<script>
var R={working:["g","работает"],idle:["y","ждёт"],
 disabled:["r","выключен"],error:["r","ошибка"],never:["r","не запускался"]};
function dot(s){return '<i class="dot '+(R[s]||R.never)[0]+'"></i>'}
function label(s){return (R[s]||R.never)[1]}
function esc(t){return String(t==null?"":t)
 .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
async function tick(){
 try{const j=await (await fetch("/api/status")).json();
  const tb=document.getElementById("tb");tb.innerHTML="";
  j.services.forEach(s=>{const tr=document.createElement("tr");
   tr.innerHTML="<td>"+dot(s.state)+"</td><td class=name>"
     +esc(s.name)+"</td><td class=st>"+label(s.state)
     +"</td><td class=det>"+esc(s.detail)+"</td>";
   tb.appendChild(tr)});
  document.getElementById("note").textContent=
   j.stale?"⚠ основной процесс не отвечает"
     :("оживление каждые 2с · "+(j.age_s!=null?("heartbeat "+j.age_s+"с"):""))}
 catch(e){document.getElementById("note").textContent="сервер недоступен"}}
tick();setInterval(tick,2000);
</script></body></html>"""


def page() -> str:
    """Возвращает готовый HTML страницы монитора."""
    return PAGE
