document.addEventListener('DOMContentLoaded',()=>{
 const dialog=document.querySelector('#new-customer-dialog'),form=document.querySelector('#new-customer-form');if(!dialog)return;
 document.querySelectorAll('[data-new-customer]').forEach(b=>b.onclick=()=>dialog.showModal());
 function reset(){form.reset();form.dataset.dirty='0';form.querySelector('[name$="-kind"]').dispatchEvent(new Event('change'));form.dataset.dirty='0';form.querySelectorAll('.passport-status,.passport-import pre,#new-customer-status').forEach(node=>node.textContent='');form.querySelectorAll('.passport-import details').forEach(node=>node.hidden=true)}
 function close(e){if(form.dataset.dirty==='1'&&!confirm('Закрыть без создания заказчика?')){e?.preventDefault();return}reset();dialog.close()}
 document.querySelectorAll('[data-close-customer]').forEach(b=>b.onclick=close);dialog.addEventListener('cancel',e=>{e.preventDefault();close()});
 form.addEventListener('submit',async e=>{
  e.preventDefault();const status=document.querySelector('#new-customer-status'),button=e.submitter;
  button.disabled=true;status.textContent='Сохраняем…';
  try{
   const r=await fetch(form.getAttribute('action'),{method:'POST',body:new FormData(form)}),data=await r.json();
   if(!r.ok){status.textContent=Object.entries(data.errors||{}).flatMap(([key,errors])=>errors.map(error=>(form.querySelector(`[for="id_customer-new-${key}"]`)?.textContent||key)+': '+error.message)).join('\n')||'Не удалось создать заказчика.';return}
   const select=document.querySelector('#contract-main-form [name=customer]');select.add(new Option(data.name,data.id,true,true));select.dispatchEvent(new Event('change',{bubbles:true}));
   reset();dialog.close();
  }catch(error){status.textContent='Не удалось связаться с сервером. Проверьте список заказчиков перед повторной отправкой.'}
  finally{button.disabled=false}
 });
});
