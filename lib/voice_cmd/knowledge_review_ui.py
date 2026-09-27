# lib/voice_cmd/knowledge_review_ui.py
"""HTML-страница доски «проверка знаний»: одна страница, 4 вкладки.

Подтверждено (галочка активна; снял → undefined), Лайя (правка
команды/параметров + подтвердить), Не распознано (кнопка
«распознать»: Laya → LLM, затем подтвердить), Сервер (статус Laya +
адрес/модель LLM). Все данные — через JSON-API knowledge_review_server.
"""

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Проверка знаний</title>
<style>
 body{font-family:system-ui;margin:1rem;background:#1e1e28;color:#eee}
 .tabs{display:flex;gap:.5rem;margin-bottom:.8rem}
 .tabs button{padding:.4rem .8rem;cursor:pointer;background:#333;color:#ddd;
  border:1px solid #555}
 .tabs button.on{background:#4a4adf;color:#fff}
 section{display:none}section.on{display:block}
 table{border-collapse:collapse;width:100%}
 td,th{border:1px solid #444;padding:.3rem .5rem;font-size:.9rem}
 input,select{background:#2a2a36;color:#eee;border:1px solid #555;
  padding:.2rem}
 button{background:#3a3a46;color:#eee;border:1px solid #666;cursor:pointer}
 .ok{color:#7d7}.bad{color:#e77}.hit{color:#999}.note{color:#999}
</style></head><body>
<div class="tabs">
 <button data-t="confirmed">Подтверждено</button>
 <button data-t="laya">Лайя</button>
 <button data-t="undefined">Не распознано</button>
 <button data-t="settings">Сервер</button>
 <button id=scan title="logs/*.log → «Не распознано»">🔍 сканировать\
 логи</button>
 <span id=scanst class=note></span>
</div>
<div><section id="t-confirmed"></section><section id="t-laya"></section>
<section id="t-undefined"></section><section id="t-settings"></section>
</div>
<script>
let S=null;
const KINDS=[["command","команда"],["start","начало"],["finish","конец"]];
async function api(p,b){const o=b?{method:"POST",headers:{
 "Content-Type":"application/json"},body:JSON.stringify(b)}:{};
 return (await fetch(p,o)).json()}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
 c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function kindSel(v){return '<select class=kind>'+KINDS.map(k=>
 `<option value="${k[0]}"${k[0]==v?" selected":""}>${k[1]}</option>`)
 .join("")+"</select>"}
function cmdSel(v){return '<select class=cmd><option value=""></option>'+
 S.commands.slice().sort().map(c=>`<option value="${esc(c)}"${c==v?" selected":""}>${
  esc(c)} — ${esc(S.descriptions[c]||"")}</option>`).join("")+"</select>"}
function row(text,e,bucket){
 const cell=e.locked
  ?'<label><input type=checkbox checked disabled> '+esc(e.source)+"</label>"
  :(bucket=="confirmed"
   ?'<label><input type=checkbox class=okc checked> подтверждено</label>'
   :"<button class=conf>✓ подтвердить</button>");
 const btns=e.locked?"":' <button class=app>сохранить</button>';
 const del=e.locked?"":'<button class=del>✕</button>';
 return `<tr data-text="${esc(text)}"><td>${del}</td><td>${esc(text)}</td>\
<td>${kindSel(e.kind||"command")}</td><td>${cmdSel(e.command)}</td>\
<td><input class=ev size=22 value="${esc(e.event)}"></td>\
<td class=hit>${e.hits||0}</td><td>${cell}${btns}</td></tr>`}
function table(bucket,title,note){
 const b=S.boards[bucket]||{};const keys=Object.keys(b).sort();
 const rows=keys.map(k=>row(k,b[k],bucket)).join("");
 const top=bucket=="undefined"?'<button id=recall>🔎 распознать все</button>'+\
' <span id=recst class=note></span>':"";
 return `<h3>${title} ${top}</h3><p class=note>${note}</p><table><tr><th></th>\
<th>фраза</th><th>вид</th><th>команда</th><th>мероприятие/параметр</th><th>hit\
</th><th></th></tr>${rows||'<tr><td colspan=7>пусто</td></tr>'}</table>`}
function settings(){
 const l=S.laya,s=S.settings;
 return `<h3>Серверы</h3><p>Laya (decision): ${l.enabled?"включена":\
"выключена"} · ${l.up?'<span class=ok>сервер жив</span>':\
'<span class=bad>сервер недоступен</span>'} · ${esc(l.url)}</p>\
<p><span class=note>Порт доски применяется после перезапуска (\
«алиса запусти проверку знаний»).</span></p>\
<p><label>Порт доски <input id=f-port size=6 value="${S.port}"></label></p>\
<p><label>LM Studio URL <input id=f-llmu size=30 value="${esc(s.llm_url)}">\
</label></p><p><label>Модель <input id=f-llmm size=30 value="\
${esc(s.llm_model)}"></label></p>\
<p><button id=savs>сохранить настройки</button></p>`}
async function load(){S=await api("/api/board");render()}
function render(){
 document.getElementById("t-confirmed").innerHTML=table("confirmed",\
"Подтверждено","Работают в рантайме: шаблоны commands.json и алиасы — "
+"только чтение; записи доски (галочка) снимаются в «Не распознано».");
 document.getElementById("t-laya").innerHTML=table("laya","Лайя",\
"Распознано Лайей или LLM, ждёт досмотра. «✓ подтвердить» сохранит "
+"правку и перенесёт в «Подтверждено».");
 document.getElementById("t-undefined").innerHTML=table("undefined",\
"Не распознано","Кнопка «распознать все» прогонит весь список по очереди: "
+"Лайя, затем LLM; распознанные фразы переедут во вкладку «Лайя».");
 document.getElementById("t-settings").innerHTML=settings()}
function pick(tr){return {text:tr.dataset.text,kind:tr.querySelector(".kind")\
.value,command:tr.querySelector(".cmd").value,\
event:tr.querySelector(".ev").value}}
async function apply(tr){const p=pick(tr);
 await api("/api/act",{action:"update",...p});await load()}
async function pollScan(){const s=await api("/api/scan"),r=document\
.querySelector("#scanst");
 r.textContent=s.running?`сканирование: ${s.done}/${s.total}, в базе \
+${s.added}`:`готово: файлов ${s.archived}, фраз ${s.phrases}, в базе \
+${s.added}`;
 if(s.running)setTimeout(pollScan,2000);else load()}
async function pollRec(){const s=await api("/api/recognize_all"),r=document\
.querySelector("#recst");
 r.textContent=s.running?`прогон: ${s.done}/${s.total}, распознано \
${s.recognized} · ${esc(s.current)}`:`готово: распознано ${s.recognized} \
из ${s.total}`;
 if(s.running)setTimeout(pollRec,2000);else load()}
document.addEventListener("click",async ev=>{
 const b=ev.target;
 if(b.dataset&&b.dataset.t){document.querySelectorAll(".tabs button")\
.forEach(x=>x.classList.toggle("on",x==b));document.querySelectorAll(\
"section").forEach(x=>x.classList.toggle("on",x.id=="t-"+b.dataset.t));\
return}
 if(b.id=="savs"){await api("/api/settings",{port:+document\
.querySelector("#f-port").value||8765,llm_url:document\
.querySelector("#f-llmu").value,llm_model:document\
.querySelector("#f-llmm").value});load();return}
 if(b.id=="scan"){document.querySelector("#scanst").textContent=\
"запуск…";await api("/api/scan",{});pollScan();return}
 if(b.id=="recall"){document.querySelector("#recst").textContent="запуск…";\
await api("/api/recognize_all",{});pollRec();return}
 const tr=b.closest?b.closest("tr"):null;if(!tr)return;
 const text=tr.dataset.text;
 if(b.classList.contains("app")){await apply(tr);return}
 if(b.classList.contains("conf")){const p=pick(tr);await api("/api/act",\
{action:"update",...p});await api("/api/act",{action:"confirm",text});\
load();return}
 if(b.classList.contains("del")){await api("/api/act",{action:"forget",\
text});load();return}});
document.addEventListener("change",async ev=>{
 const c=ev.target;if(!c.classList||!c.classList.contains("okc"))return;
 await api("/api/act",{action:c.checked?"confirm":"demote",\
text:c.closest("tr").dataset.text});load()});
load();
</script></body></html>
"""
