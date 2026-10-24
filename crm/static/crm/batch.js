document.addEventListener('DOMContentLoaded',()=>{
 const progress=document.querySelector('[data-batch]');if(!progress)return;
 const form=document.querySelector('#batch-plan'),status=document.querySelector('#batch-status'),resume=document.querySelector('#batch-resume'),pause=document.querySelector('#batch-pause');let running=false;
 document.querySelector('#batch-select-new')?.addEventListener('click',()=>{const boxes=[...form.querySelectorAll('[name=selected]')],check=boxes.some(b=>!b.checked);boxes.forEach(b=>b.checked=check)});
 form.querySelectorAll('[data-batch-row]').forEach(input=>input.addEventListener('input',()=>input.dataset.manual='1'));
 form.querySelectorAll('[data-batch-end]').forEach(end=>end.addEventListener('change',()=>{
  form.querySelectorAll(`[data-batch-row="${end.dataset.batchEnd}"]`).forEach(input=>{if(input.dataset.manual==='1'||input.dataset.taskAnchor!=='end'||!end.value)return;const date=new Date(end.value+'T12:00:00Z');date.setUTCDate(date.getUTCDate()+Number(input.dataset.taskOffset));input.value=[date.toISOString().slice(0,10),input.dataset.created].sort().at(-1)});
 }));
 function controls(){if(resume)resume.hidden=running;if(pause)pause.hidden=!running}
 async function run(){
  if(running||!resume)return;running=true;controls();status.textContent='Загружаем по одной заявке. Можно поставить очередь на паузу.';
  try{
   while(running){
    const response=await fetch(progress.dataset.stepUrl,{method:'POST',headers:{'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value}});
    if(!response.headers.get('content-type')?.includes('application/json'))throw Error('Сервер не завершил запрос. Обновите страницу, чтобы проверить результат.');
    const result=await response.json();if(!response.ok)throw Error(result.error||'Не удалось продолжить загрузку.');
    Object.entries(result.counts).forEach(([key,value])=>progress.querySelector(`[data-count="${key}"]`).textContent=value);
    if(result.row){const row=document.querySelector('#batch-row-'+result.row.id);row.dataset.state=result.row.state;row.querySelector('[data-row-state]').textContent=result.row.state==='done'?'Создан / уже создан':'Ошибка';row.querySelector('[data-row-message]').textContent=result.row.message;
     if(result.row.url){const a=document.createElement('a');a.href=result.row.url;a.textContent='Открыть договор';row.append(a)}}
    if(result.finished){running=false;status.textContent='Очередь завершена. Проверьте результаты каждой заявки.';resume.hidden=true;pause.hidden=true;const reload=document.createElement('a');reload.href=location.pathname;reload.textContent='Показать итог и повторить выбранные ошибки';status.append(' ',reload);return}
   }
   status.textContent='Пауза. Текущий запрос завершён; можно продолжить очередь.';
  }catch(error){status.textContent=error.message+' Созданные договоры сохранены. Обновите страницу или нажмите «Продолжить загрузку».';running=false}
  controls();
 }
 resume?.addEventListener('click',run);pause?.addEventListener('click',()=>{running=false;status.textContent='Останавливаем отправку следующих заявок; текущий запрос завершается…'});
 if(progress.dataset.auto==='1'){history.replaceState(null,'',location.pathname);run()}
});
