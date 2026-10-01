# lib/voice_cmd/knowledge_review_ui.py
"""HTML-страница доски «проверка знаний»: 5 вкладок, данные через JSON-API.
✕ в «Подтверждено» чистит фразу из commands.json и базы; на «Лайе» снимает
догадку ИИ. Команда — select, у free-text (кроме taskstart/taskdone) — «ключ»."""

PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>Проверка знаний</title>
<style>
 body{font-family:system-ui;margin:1rem;background:#1e1e28;color:#eee}
 .tabs{display:flex;gap:.5rem;margin-bottom:.8rem}
 .tabs button{padding:.4rem .8rem;cursor:pointer;background:#333;color:#ddd;border:1px solid #555}
 .tabs button.on{background:#4a4adf;color:#fff}
 section{display:none}section.on{display:block}
 table{border-collapse:collapse;width:100%}
 td,th{border:1px solid #444;padding:.3rem .5rem;font-size:.9rem}
 input,select{background:#2a2a36;color:#eee;border:1px solid #555;padding:.2rem}
 select.cmd{max-width:11rem} .cdd{font-size:.75rem;color:#999;margin-top:.15rem}
 .ti{font-size:.78rem;color:#cde;cursor:pointer;padding:.05rem .1rem}
 .ti:hover{background:#3a3a56} .tlist{max-height:11rem;overflow:auto}
 .tasks{color:#999;font-size:.8rem;margin-top:.2rem;border-top:1px dashed #444}
 button{background:#3a3a46;color:#eee;border:1px solid #666;cursor:pointer}
 .ok{color:#7d7}.bad{color:#e77}.hit{color:#999}.note{color:#999}
</style></head><body>
<div class="tabs">
 <button data-t="confirmed">Подтверждено</button>
 <button data-t="laya">Лайя</button>
 <button data-t="undefined">Не распознано</button>
 <button data-t="stats">Статистика</button> <button data-t="settings">Сервер</button>
 <button id=scan title="logs/*.log → «Не распознано»">🔍 сканировать\
 логи</button>
 <span id=scanst class=note></span>
</div>
<div><section id="t-confirmed"></section><section id="t-laya"></section>
<section id="t-undefined"></section><section id="t-settings"></section>
</div><section id="t-stats"></section>
<script>
let S=null,T=null;  // T — задачи real_life_tasks (null = не запрашивались)
async function api(p,b){const o=b?{method:"POST",headers:{
 "Content-Type":"application/json"},body:JSON.stringify(b)}:{};
 return (await fetch(p,o)).json()}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,
 c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function trunc(s,n){s=String(s==null?"":s);return s.length>n?s.slice(0,n)+"…":s}
function cmdSel(v){return '<select class=cmd><option value=""></option>'+
 S.commands.slice().sort().map(c=>`<option value="${esc(c)}"${c==v?" selected":""}\
 title="${esc(c)} — ${esc(S.descriptions[c]||"")}">${
  esc(trunc(c,18))}</option>`).join("")+"</select>"}
function cmdNote(v){return `<div class=cdd>${v?esc(v)+" — \
"+esc(S.descriptions[v]||""):"&nbsp;"}</div>`}
function nk(s){return String(s==null?"":s).toLowerCase().replace(/ё/g,"е")
 .replace(/\\s+/g," ").trim()}
function afterKey(ph,key){ph=nk(ph);key=nk(key);
 return !key||ph.indexOf(key)!=0?ph:nk(ph.slice(key.length))}
function isFree(c){return (S.freeText||[]).indexOf(c)>=0
 &&c!="taskstart"&&c!="taskdone"}  // у них параметр — задача из списка
function keySel(t,chosen){const w=nk(t).split(" ");if(w.length<2)return "";
 const ps=w.slice(0,-1).map((_,i)=>w.slice(0,i+1).join(" "));
 return '<br><select class=key><option value="">ключ…</option>'+ps.map(p=>
  `<option${p==chosen?" selected":""}>${esc(p)}</option>`).join("")+"</select>"}
function cmdCell(cmd,text,ev){const t=nk(text),e=nk(ev||""),
 k=e&&t.length>e.length&&t.endsWith(e)?t.slice(0,-e.length).trim():"";
 return cmdSel(cmd)+(isFree(cmd)?keySel(text,k):"")+cmdNote(cmd)}
function taskList(){return (T&&T.length)?T.map(t=>
 `<div class=ti title="подставить в параметр">${esc(trunc(t,60))}</div>`
 ).join(""):'<span class=note>задачи из таблицы не найдены</span>'}
function tasksBox(){return `<div class=tasks><input class=tf size=14
 placeholder="фильтр задач">\
<div class=tlist>${T?taskList():'<span class=note>загрузка задач…</span>'}
</div></div>`}
function filterTasks(inp){const q=inp.value.trim().toLowerCase();
 inp.nextElementSibling.querySelectorAll(".ti").forEach(x=>
  x.style.display=x.textContent.toLowerCase().includes(q)?"":"none")}
async function ensureTasks(){if(T)return;try{T=(await api("/api/tasks")).tasks||
 []}catch(e){T=[]}
 document.querySelectorAll(".tasks").forEach(x=>x.querySelector(".tlist")
 .innerHTML=taskList())}
function syncRow(tr){const box=tr.querySelector(".tasks"),
 cmd=tr.querySelector(".cmd").value,
 task=cmd=="taskstart"||cmd=="taskdone";
 tr.querySelector(".cc").innerHTML=cmdCell(cmd,tr.dataset.text,tr.querySelector(".ev").value);
 if(task){if(!box&&tr.querySelector(".app")){tr
  .querySelectorAll("td")[3].insertAdjacentHTML("beforeend",tasksBox());
  ensureTasks()}}
 else if(box)box.remove()}
function row(text,e,bucket){
 const cell=e.locked
  ?'<label><input type=checkbox checked disabled> '+esc(e.source)+"</label>"
  :(bucket=="confirmed"
   ?'<label><input type=checkbox class=okc checked> подтверждено</label>'
   :"<button class=conf>✓ подтвердить</button>");
 const btns=e.locked?"":' <button class=app>сохранить</button>';
 // ✕: в «Подтверждено» чистит фразу из commands.json И базы (purge);
 // на «Лайе» снимает догадку ИИ (reset); в «Не распознано» удаляет (forget).
 const del=bucket=="confirmed"
  ?'<button class=del title="удалить из commands.json и базы знаний">✕</button>'
  :(e.locked?"":'<button class=del>✕</button>');
 const task=e.command=="taskstart"||e.command=="taskdone";
 const extra=!e.locked&&task?tasksBox():"";
 return `<tr data-text="${esc(text)}" data-bucket="${bucket}" data-kind=\
"${e.kind||"command"}"><td>${del}</td><td>${esc(text)}</td>\
<td class=cc>${cmdCell(e.command,text,e.event)}</td>\
<td><input class=ev size=22 value="${esc(e.event)}">${extra}</td>\
<td class=hit>${e.hits||0}</td><td>${cell}${btns}</td></tr>`}
function table(bucket,title,note){
 const b=S.boards[bucket]||{};const keys=Object.keys(b).sort();
 const rows=keys.map(k=>row(k,b[k],bucket)).join("");
 const top=bucket=="undefined"?'<button id=recall>🔎 распознать все</button>'+\
' <span id=recst class=note></span>':"";
 return `<h3>${title} ${top}</h3><p class=note>${note}</p><table><tr><th></th>\
<th>фраза</th><th>команда</th><th>мероприятие/параметр</th><th>hit</th><th></th>\
</tr>${rows||'<tr><td colspan=6>пусто</td></tr>'}</table>`}
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
"Подтверждено","Работают в рантайме: шаблоны commands.json — только "
+"чтение; записи доски (галочка) снимаются в «Не распознано». ✕ удаляет "
+"устаревшую фразу из commands.json и базы знаний.");
 document.getElementById("t-laya").innerHTML=table("laya","Лайя",\
"Распознано Лайей или LLM, ждёт досмотра. «✓ подтвердить» сохранит "
+"правку и перенесёт в «Подтверждено».");
 document.getElementById("t-undefined").innerHTML=table("undefined",\
"Не распознано","Кнопка «распознать все» прогонит весь список по очереди: "
+"Лайя, затем LLM; распознанные фразы переедут во вкладку «Лайя».");
 document.getElementById("t-stats").innerHTML=S.stats||"";
 document.getElementById("t-settings").innerHTML=settings()
 if(document.querySelector(".tasks")&&!T)ensureTasks()}
function pick(tr){return {text:tr.dataset.text,kind:tr.dataset.kind||"command",\
command:tr.querySelector(".cmd").value,event:tr.querySelector(".ev").value}}
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
 if(b.classList.contains("ti")){tr.querySelector(".ev").value=
  b.textContent.trim();return}
 if(b.classList.contains("app")){await apply(tr);return}
 if(b.classList.contains("conf")){const p=pick(tr);await api("/api/act",
  {action:"update",...p});await api("/api/act",{action:"confirm",text});
  load();return}
 if(b.classList.contains("del")){
  if(tr.dataset.bucket=="confirmed"){
   if(!confirm("Удалить фразу «"+text+"» из commands.json и базы знаний?"))
    return;
   await api("/api/act",{action:"purge",text});
  }else{await api("/api/act",
   {action:tr.dataset.bucket=="laya"?"reset":"forget",text});}
  load();return}});
document.addEventListener("input",ev=>{
 const c=ev.target;
 if(c.classList&&c.classList.contains("tf"))filterTasks(c)});
document.addEventListener("change",async ev=>{
 const c=ev.target;
 if(c.classList&&c.classList.contains("cmd")&&c.closest("tr"))
  syncRow(c.closest("tr"));
 if(c.classList&&c.classList.contains("key")){const tr=c.closest("tr");
  tr.querySelector(".ev").value=afterKey(tr.dataset.text,c.value);return}
 if(!c.classList||!c.classList.contains("okc"))return;
 await api("/api/act",{action:c.checked?"confirm":"demote",\
text:c.closest("tr").dataset.text});load()});
load();
</script></body></html>
"""
