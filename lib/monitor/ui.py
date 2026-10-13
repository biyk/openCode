# TOOLTIP: Вкладка «Сервисы» для страницы доски знаний: таблица живости с автообновлением
"""GUI монитора — не отдельная страница, а вкладка на сервере доски знаний.

`install(board_html)` вставляет TAB перед `</body>`: скрипт добавляет кнопку
с `data-t="services"` в `.tabs` доски и `<section id="t-services">` — и
штатный обработчик кликов доски сам переключает вкладку по этим атрибутам.
Содержимое тянется из `/api/monitor` (heartbeat основного процесса + пробы
портов) раз в 2 с, но только когда вкладка видна: фоновый опрос не должен
мешать досмотру знаний.

Внутри строки нет backslash-продолжений и шаблонных литералов — они ломали
сборку JS (§4.5).
"""

TAB_ID = "services"

TAB = """<style>
 .dot{width:11px;height:11px;border-radius:50%;display:inline-block;margin-right:.3rem}
 .dg{background:#3fb950}.dy{background:#d29922}.dr{background:#f85149}
 #t-services .nm{font-weight:600}#t-services .dt{color:#9a9ab0;font-size:.85rem}
</style>
<script>
(function(){
 var R={working:["dg","работает"],idle:["dy","ждёт"],disabled:["dr","выключен"],
        error:["dr","ошибка"],never:["dr","не запускался"]};
 var tabs=document.querySelector(".tabs");if(!tabs)return;
 var b=document.createElement("button");b.dataset.t="services";
 b.textContent="Сервисы";
 b.title="фоновые потоки и внешние процессы: зелёный работает, жёлтый ждёт, красный лежит";
 tabs.appendChild(b);
 var sec=document.createElement("section");sec.id="t-services";
 document.body.appendChild(sec);
 var force=false;
 function esc(t){return String(t==null?"":t).replace(/&/g,"&amp;")
  .replace(/</g,"&lt;").replace(/>/g,"&gt;")}
 function row(s){var st=R[s.state]||R.never;
  return "<tr><td><i class='dot "+st[0]+"'></i></td><td class=nm>"+esc(s.name)+
   "</td><td>"+st[1]+"</td><td class=dt>"+esc(s.detail)+"</td></tr>"}
 async function tick(){
  if(!force&&!sec.classList.contains("on"))return;   // скрытая вкладка не грузит сервер
  force=false;
  try{
   var j=await (await fetch("/api/monitor")).json();
   var age=(j.age_s==null?"—":j.age_s+" с");
   var h="<h3>Монитор сервисов</h3><p class=note>"+(j.stale?
     "⚠ основной процесс не отвечает (heartbeat "+age+")":
     "оживление каждые 2 с · heartbeat "+age)+"</p>";
   h+="<table><tr><th></th><th>сервис</th><th>состояние</th>";
   h+="<th>подробности</th></tr>";
   j.services.forEach(function(s){h+=row(s)});
   sec.innerHTML=h+"</table>";
  }catch(e){
   sec.innerHTML="<h3>Монитор сервисов</h3><p class=note>"+
     "нет ответа /api/monitor — перезапустите сервер доски</p>"}
 }
 b.addEventListener("click",function(){force=true;tick()});
 tick();setInterval(tick,2000);
 if(location.hash==="#services")b.click();
})();
</script>"""


def install(board_html: str) -> str:
    """Вставляет вкладку монитора в HTML страницы доски (перед </body>)."""
    return board_html.replace("</body>", TAB + "\n</body>", 1)


__all__ = ["TAB", "TAB_ID", "install"]
