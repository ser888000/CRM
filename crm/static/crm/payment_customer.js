document.addEventListener('DOMContentLoaded',()=>{
 const customer=document.querySelector('#id_customer'),contract=document.querySelector('#id_contract');
 if(!customer||!contract)return;
 let sequence=0;
 customer.addEventListener('change',async()=>{
  const current=++sequence,selected=contract.value;contract.disabled=true;
  try{
   const response=await fetch(''+ '/admin/crm/payment/contracts-for-customer/?customer='+encodeURIComponent(customer.value));
   if(!response.ok)throw new Error('Не удалось получить договоры');
   const data=await response.json();if(current!==sequence)return;
   contract.replaceChildren(new Option('---------',''));
   data.contracts.forEach(c=>contract.add(new Option(c.label,c.id,false,String(c.id)===selected)));
  }catch(e){if(current===sequence){contract.replaceChildren(new Option('Ошибка загрузки — обновите страницу',''));}}
  finally{if(current===sequence)contract.disabled=false;}
 });
});
