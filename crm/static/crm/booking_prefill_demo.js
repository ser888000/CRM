/* Synthetic-data probe; deliberately limited to the agency's booking page. */
(()=>{
 'use strict';
 const origins=new Set(['https://aborigen-tour.ru','https://www.aborigen-tour.ru']);
 if(!origins.has(location.origin)||location.pathname!=='/book/offers_tourv.php'||window.__aborigenPrefillProbe)return;
 const script=document.currentScript;
 if(!script)return;
 const endpoint=new URL('/booking-prefill/demo/',script.src);
 if(endpoint.origin!=='https://crm.aborigen-tour.ru')return;
 window.__aborigenPrefillProbe=true;
 let saved=null,panel,button,status,reset;
 const clone=value=>JSON.parse(JSON.stringify(value));
 async function authorize(){
  const response=await fetch(endpoint,{credentials:'include',cache:'no-store',redirect:'error'});
  if(!response.ok)return null;
  const data=await response.json();return data.enabled&&data.test_only?data:null;
 }
 function refresh(){
  const seen=new Set();let count=0;
  function visit(node,depth){
   if(!node||typeof node!=='object'||depth>5||seen.has(node))return;
   seen.add(node);
   if(node._tourBuyForm&&typeof node._tourBuyForm.update==='function'){
    node._tourBuyForm.update({IsForceUpdate:true});count++;
   }
   for(const key of ['_instance','_orderPage','_tourOrder','_orderControl','_widget','_orderForm','_tourBookingControl'])visit(node[key],depth+1);
  }
  visit(window.TV?.orderManager,0);return count;
 }
 async function fill(){
  button.disabled=true;
  try{
   const data=await authorize();if(!data){panel.remove();return;}
   if(typeof window.initTv==='function')window.initTv();
   const catalog=window.TV?.orderCatalog;
   if(!catalog||!['getTouristsData','getCustomerData','setTouristsData','setCustomerData'].every(key=>typeof catalog[key]==='function'))throw Error('Форма открыта, но функции подстановки не доступны. Диагностика: initTv='+typeof window.initTv+'; TV='+typeof window.TV+'; orderCatalog='+typeof catalog+'; методы='+['getTouristsData','getCustomerData','setTouristsData','setCustomerData'].map(key=>key+':'+typeof catalog?.[key]).join(', '));
   const tourists=catalog.getTouristsData(),customer=catalog.getCustomerData();
   if(!Array.isArray(tourists)||tourists.length!==2||tourists.some(person=>person.Age!==0)||!customer||!Object.prototype.hasOwnProperty.call(customer,'DocumentType'))throw Error('Для теста откройте пустую форму на двух взрослых туристов.');
   const personalTourist=['NAME','SURNAME','BIRTHDAY','PASSPORTNUMBER','PASSPORTISSUE','PASSPORTEXPIRY','PASSPORTAUTHORITY'];
   const personalCustomer=['Name','Phone','Email','Birthday','Address','PassportNumber'];
   if(tourists.some(person=>personalTourist.some(key=>Boolean(person[key])))||personalCustomer.some(key=>Boolean(customer[key])))throw Error('В форме уже есть данные. Тест их не заменяет — откройте пустую форму.');
   saved={catalog,tourists:clone(tourists),customer:clone(customer),hash:location.hash,tourId:window.TV?.orderManager?._TourId};
   try{
    catalog.setTouristsData(tourists.map((person,index)=>({...person,...data.tourists[index]})));
    catalog.setCustomerData({...customer,...data.customer});
    const refreshed=refresh();
    reset.hidden=false;
    status.textContent=refreshed?'ТЕСТОВЫЕ ДАННЫЕ. Проверьте поля; заявку не отправляйте.':'Данные подготовлены. Для отображения попробуйте заново открыть форму. Заявку не отправляйте.';
   }catch(error){catalog.setTouristsData(saved.tourists);catalog.setCustomerData(saved.customer);saved=null;throw error;}
  }catch(error){status.textContent=error.message||'Не удалось выполнить тест.';}
  finally{button.disabled=false;}
 }
 function show(){
  if(!document.querySelector('.tv-moduleid-898'))return;
  panel=document.createElement('aside');panel.setAttribute('aria-label','Тест заполнения из CRM');
  Object.assign(panel.style,{position:'fixed',left:'16px',bottom:'16px',zIndex:'2147483000',maxWidth:'330px',padding:'14px',border:'2px solid #183f35',borderRadius:'10px',background:'#fffbe9',color:'#183f35',font:'14px sans-serif',boxShadow:'0 3px 16px #0003'});
  const title=document.createElement('strong');title.textContent='CRM · тест для сотрудника';
  button=document.createElement('button');button.type='button';button.textContent='Заполнить тестовыми данными';button.onclick=fill;
  status=document.createElement('p');status.setAttribute('role','status');status.textContent='Откройте пустую форму покупки на двух взрослых туристов.';
  reset=document.createElement('button');reset.type='button';reset.textContent='Убрать тестовые данные';reset.hidden=true;
  reset.onclick=()=>{if(!saved)return;if(saved.hash!==location.hash||saved.tourId!==window.TV?.orderManager?._TourId){status.textContent='Вы открыли другой тур. Восстановление старой формы отменено.';return;}saved.catalog.setTouristsData(saved.tourists);saved.catalog.setCustomerData(saved.customer);refresh();saved=null;reset.hidden=true;status.textContent='Исходные данные формы восстановлены.';};
  panel.append(title,document.createElement('br'),button,status,reset);document.body.append(panel);
 }
 async function init(){try{if(await authorize())show();}catch{/* Public visitors see no UI or technical errors. */}}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
