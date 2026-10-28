document.addEventListener('DOMContentLoaded',()=>{
 const csrf=document.querySelector('#operator-paid-csrf [name=csrfmiddlewaretoken]')?.value;
 document.querySelectorAll('[data-operator-paid]').forEach(button=>button.addEventListener('click',async()=>{
  if(button.disabled||!csrf)return;
  button.disabled=true;
  const data=new FormData();data.set('csrfmiddlewaretoken',csrf);data.set('version',button.dataset.version);data.set('paid',button.dataset.value==='1'?'0':'1');
  try{
   const response=await fetch(button.dataset.operatorPaid,{method:'POST',body:data,headers:{'Accept':'application/json'}});
   if(!response.ok){let result;try{result=await response.json()}catch{};throw Error(result?.error||'Не удалось сохранить статус. Обновите страницу перед повтором.')}
   const result=await response.json();button.dataset.value=result.paid?'1':'0';button.dataset.version=result.version;
   button.classList.toggle('is-paid',result.paid);button.setAttribute('aria-pressed',String(result.paid));button.textContent=result.paid?'✓ Оплачено':'○ Не оплачено';
   document.querySelectorAll('input[name=version]').forEach(field=>field.value=result.version);
  }catch(error){alert(error.message||'Не удалось связаться с сервером. Обновите страницу для проверки статуса.')}
  finally{button.disabled=false}
 }));
});
