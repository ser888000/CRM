document.addEventListener('DOMContentLoaded',()=>{
 const status=document.querySelector('#legacy-status'),result=document.querySelector('#legacy-result');
 async function refresh(){
  try{const response=await fetch('/management/legacy/status/',{cache:'no-store',headers:{'Accept':'application/json'}});if(!response.ok)throw Error();const data=await response.json();status.textContent=data.message||'Загрузка ещё не запускалась.';if(data.run_id){result.href='/management/legacy/report/'+data.run_id+'/';result.hidden=false;}if(['running','queued'].includes(data.state))setTimeout(refresh,3000);else document.querySelectorAll('#legacy-import-form button,form[action$="/clear/"] button').forEach(button=>button.disabled=false);}
  catch(e){status.textContent='Связь временно недоступна. Проверим состояние ещё раз.';setTimeout(refresh,5000);}
 }
 refresh();
});
