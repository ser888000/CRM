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
 async function authorize(){
  const response=await fetch(endpoint,{credentials:'include',cache:'no-store',redirect:'error'});
  if(!response.ok)return null;
  const data=await response.json();return data.enabled&&data.test_only?data:null;
 }
 const touristFields={SURNAME:'TVTouristSurname',NAME:'TVTouristName',BIRTHDAY:'TVTouristBirthday',PASSPORTNUMBER:'TVPassportNumber',PASSPORTISSUE:'TVPassportIssue',PASSPORTEXPIRY:'TVPassportExpiry',PASSPORTAUTHORITY:'TVPassportAuthority'};
 const customerFields={Name:'TVCustomerContactsName',Phone:'TVCustomerContactsPhone',Email:'TVCustomerContactsEmail',Address:'TVCustomerContactsAddress',Birthday:'TVCustomerContactsBirthday',PassportNumber:'TVCustomerContactsPassportNumber',PassportIssue:'TVCustomerContactsPassportIssue',PassportAuthority:'TVCustomerContactsPassportAuthority',PassportAuthorityCode:'TVCustomerContactsPassportAuthorityCode'};
 const visible=selector=>[...document.querySelectorAll(selector)].filter(node=>node.getClientRects().length);
 function inputFor(binding){
  const selector='.'+binding.className+' input';
  const matches=binding.person===undefined?visible(selector):[...(visible('.TVTourBuyTouristItemControl')[binding.person]?.querySelectorAll(selector)||[])].filter(node=>node.getClientRects().length);
  if(matches.length!==1||matches[0].disabled||matches[0].readOnly)throw Error('Поле '+binding.className+' не найдено однозначно или недоступно. Откройте форму покупки.');
  return matches[0];
 }
 function setInput(binding,value){
  const input=inputFor(binding);
  const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;
  if(!setter)throw Error('Браузер не поддерживает подстановку.');
  setter.call(input,value);
  // The actual Tourvisor InputNew control listens for input; blur updates labels/masks.
  input.dispatchEvent(new Event('input',{bubbles:true}));
  inputFor(binding).dispatchEvent(new Event('change',{bubbles:true}));
  inputFor(binding).dispatchEvent(new Event('blur'));
 }
 function restore(){
  if(!saved)return;
  if(saved.hash!==location.hash){status.textContent='Вы открыли другой тур. Восстановление старой формы отменено.';return;}
  try{
   for(const binding of saved.bindings)if(inputFor(binding)!==binding.node)throw Error('Форма была открыта заново. Старое состояние к ней не применяется.');
   for(const binding of saved.bindings)setInput(binding,binding.before);
   saved=null;reset.hidden=true;status.textContent='Исходные данные формы восстановлены.';
  }catch(error){status.textContent=error.message;}
 }
 async function fill(){
  button.disabled=true;
  try{
   const data=await authorize();if(!data){panel.remove();return;}
   const people=visible('.TVTourBuyTouristItemControl');
   if(people.length!==2||people.some(node=>!/^Взрослый турист/.test(node.querySelector('.TVTourBuyTouristItemHeader')?.textContent.trim()||'')))throw Error('Для теста откройте пустую форму на двух взрослых туристов.');
   const bindings=[];
   for(let person=0;person<2;person++)for(const [key,className] of Object.entries(touristFields))bindings.push({person,className,value:data.tourists[person][key]});
   for(const [key,className] of Object.entries(customerFields))bindings.push({className,value:data.customer[key]});
   for(const binding of bindings){
    const node=inputFor(binding);binding.before=node.value;binding.node=node;
    const content=node.value.replace(/[\s_().+\-]/g,'');
    if(content&&(binding.className!=='TVCustomerContactsPhone'||content!=='7'))throw Error('В форме уже есть данные. Тест их не заменяет — откройте пустую форму.');
   }
   saved={hash:location.hash,bindings};
   try{
    for(const binding of bindings)setInput(binding,binding.value);
    reset.hidden=false;status.textContent='ТЕСТОВЫЕ ДАННЫЕ заполнены. Проверьте поля; заявку не отправляйте.';
   }catch(error){reset.hidden=false;restore();throw error;}
  }catch(error){status.textContent=error.message||'Не удалось выполнить тест.';}
  finally{button.disabled=false;}
 }
 function diagnostics(){
  const address=value=>{try{const url=new URL(value,location.href);return url.origin+url.pathname}catch{return 'unavailable'}};
  const fields=[...document.querySelectorAll('input,select,textarea')].filter(node=>!panel?.contains(node)&&node.getClientRects().length&&node.type!=='hidden').slice(0,100).map(node=>{
   const parents=[];let parent=node.parentElement;
   for(let depth=0;parent&&depth<5;depth++,parent=parent.parentElement)parents.push({tag:parent.tagName,classes:String(parent.className||'').slice(0,240)});
   return {tag:node.tagName,type:node.type||'',name:node.name||'',id:node.id||'',placeholder:node.getAttribute('placeholder')||'',classes:String(node.className||'').slice(0,240),parents};
  });
  return JSON.stringify({probe_version:4,page:address(location.href),runtime:{TV:typeof window.TV,initTv:typeof window.initTv,keys:Object.keys(window.TV||{}).sort().slice(0,160)},scripts:[...document.scripts].filter(node=>node.src).map(node=>address(node.src)),frames:[...document.querySelectorAll('iframe')].map(node=>address(node.src)),fields},null,2);
 }
 function show(){
  if(!document.querySelector('.tv-moduleid-898'))return;
  panel=document.createElement('aside');panel.setAttribute('aria-label','Тест заполнения из CRM');
  Object.assign(panel.style,{position:'fixed',left:'16px',bottom:'16px',zIndex:'2147483000',maxWidth:'330px',padding:'14px',border:'2px solid #183f35',borderRadius:'10px',background:'#fffbe9',color:'#183f35',font:'14px sans-serif',boxShadow:'0 3px 16px #0003'});
  const title=document.createElement('strong');title.textContent='CRM · тест для сотрудника';
  button=document.createElement('button');button.type='button';button.textContent='Заполнить тестовыми данными';button.onclick=fill;
  status=document.createElement('p');status.setAttribute('role','status');status.textContent='Откройте пустую форму покупки на двух взрослых туристов.';
  reset=document.createElement('button');reset.type='button';reset.textContent='Убрать тестовые данные';reset.hidden=true;
  reset.onclick=restore;
  const diagnosticButton=document.createElement('button');diagnosticButton.type='button';diagnosticButton.textContent='Скопировать диагностику';
  diagnosticButton.onclick=async()=>{
   const text=diagnostics();
   try{await navigator.clipboard.writeText(text);status.textContent='Диагностика скопирована. Пришлите её в чат. Значения полей в отчёт не включены.';}
   catch{const output=document.createElement('textarea');output.readOnly=true;output.value=text;output.rows=8;output.style.width='100%';panel.append(output);output.select();status.textContent='Скопируйте этот отчёт и пришлите в чат.';}
  };
  panel.append(title,document.createElement('br'),button,status,reset,document.createElement('br'),diagnosticButton);document.body.append(panel);
 }
 async function init(){try{if(await authorize())show();}catch{/* Public visitors see no UI or technical errors. */}}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
