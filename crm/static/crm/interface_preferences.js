document.addEventListener('DOMContentLoaded',()=>{
 const form=document.querySelector('#interface-preferences'),selector=document.querySelector('#interface-theme');
 let preferences={theme:document.body.dataset.theme||'accounting',column_widths:{}};
 try{preferences=JSON.parse(document.querySelector('#interface-preferences-data').textContent)}catch(e){}
 const status=document.querySelector('#interface-preferences-status');
 function message(text,error=false){if(status){status.textContent=text;status.classList.toggle('error',error)}}
 let queue=Promise.resolve();
 async function persist(patch){
  if(!form)throw new Error('Настройки недоступны');
  message('Сохранение…');
  const response=await fetch(form.action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:JSON.stringify(patch),credentials:'same-origin',cache:'no-store'});
  if(!response.ok)throw new Error('Настройки не сохранены');
  preferences=await response.json();message('Сохранено');return preferences;
 }
 window.crmInterface={get preferences(){return preferences},save(patch){const result=queue.catch(()=>{}).then(()=>persist(patch));queue=result;result.catch(()=>message('Не удалось сохранить. Повторите изменение.',true));return result}};
 if(selector){
  let current=preferences.theme;
  selector.addEventListener('change',async()=>{
   const next=selector.value,previous=current;selector.disabled=true;document.body.dataset.theme=next;document.dispatchEvent(new Event('crm:layout'));
   try{await window.crmInterface.save({theme:next});current=next}
   catch(e){selector.value=previous;document.body.dataset.theme=previous;document.dispatchEvent(new Event('crm:layout'))}
   finally{selector.disabled=false}
  });
 }
 if(form)form.addEventListener('submit',event=>event.preventDefault());
});
