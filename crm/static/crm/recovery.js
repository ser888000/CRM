document.addEventListener('DOMContentLoaded',()=>{
 const form=document.getElementById('recovery-form'),message=document.getElementById('recovery-message'),link=document.getElementById('recovery-download');
 let timer;
 const date=value=>{const parsed=new Date(value);return Number.isNaN(parsed.getTime())?'':parsed.toLocaleString('ru-RU')};
 async function refresh(){
  try{
   const response=await fetch('/management/backups/status/',{cache:'no-store'});if(!response.ok)throw Error();
   const data=await response.json(),manual=data.manual;
   form.querySelectorAll('button').forEach(button=>button.disabled=!manual.installed||manual.busy);
   message.textContent=manual.busy?'Копия готовится. Можно продолжать работу в CRM.':manual.message||'Создайте свежую копию перед скачиванием.';
   const ready=manual.last_success||(manual.state==='ready'?manual:null);
   link.hidden=!ready?.request_id;
   if(ready?.request_id){link.href='/management/backups/download/'+encodeURIComponent(ready.request_id)+'/';link.textContent='Скачать '+(ready.kind==='full'?'полный архив':'копию базы')+' ('+(ready.bytes/1024/1024).toFixed(1)+' МБ)'}
   const remote=data.remote;
   document.getElementById('recovery-remote').textContent=remote.last_success?('Последняя проверенная внешняя копия: '+date(remote.last_success.finished)+(remote.state==='failed'?'. Последняя попытка завершилась ошибкой.':remote.state==='running'?'. Создаётся новая копия.':'')):(remote.message||'Внешнее хранилище пока не настроено или первая копия ещё не проверена.');
   document.getElementById('recovery-schedule').textContent=data.scheduled?'Ежедневное копирование включено: 03:30 по Москве.':'Ежедневная отправка во внешнее хранилище пока не включена.';
   timer=setTimeout(refresh,manual.busy||remote.state==='running'?2000:15000);
  }catch(error){message.textContent='Не удалось обновить статус. Обновите страницу.';timer=setTimeout(refresh,10000)}
 }
 form.addEventListener('submit',()=>clearTimeout(timer));refresh();
});
