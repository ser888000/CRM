/* Employee-only booking prefill. Never submits a Tourvisor request. */
(()=>{
 'use strict';
 const origins=new Set(['https://aborigen-tour.ru','https://www.aborigen-tour.ru']);
 if(!origins.has(location.origin)||location.pathname!=='/book/offers_tourv.php'||window.__aborigenBookingPrefill)return;
 const script=document.currentScript;
 if(!script)return;
 const endpoint=new URL('/booking-prefill/status/',script.src);
 if(endpoint.origin!=='https://crm.aborigen-tour.ru')return;
 window.__aborigenBookingPrefill=true;
 let saved=null,panel,button,status,reset;
 async function authorize(){
  const response=await fetch(endpoint,{credentials:'include',cache:'no-store',redirect:'error'});
  if(!response.ok)return null;
  const data=await response.json();return data.enabled?data:null;
 }
 const touristFields={SURNAME:'TVTouristSurname',NAME:'TVTouristName',BIRTHDAY:'TVTouristBirthday',PASSPORTNUMBER:'TVPassportNumber',PASSPORTISSUE:'TVPassportIssue',PASSPORTEXPIRY:'TVPassportExpiry',PASSPORTAUTHORITY:'TVPassportAuthority'};
 const customerFields={Name:'TVCustomerContactsName',Phone:'TVCustomerContactsPhone',Email:'TVCustomerContactsEmail',Address:'TVCustomerContactsAddress',Birthday:'TVCustomerContactsBirthday',PassportNumber:'TVCustomerContactsPassportNumber',PassportIssue:'TVCustomerContactsPassportIssue',PassportAuthority:'TVCustomerContactsPassportAuthority',PassportAuthorityCode:'TVCustomerContactsPassportAuthorityCode'};
 const visible=selector=>[...document.querySelectorAll(selector)].filter(node=>node.getClientRects().length);
 function inputFor(binding){
  const selector='.'+binding.className+(binding.kind==='gender'?'':' input');
  const matches=binding.person===undefined?visible(selector):[...(visible('.TVTourBuyTouristItemControl')[binding.person]?.querySelectorAll(selector)||[])].filter(node=>node.getClientRects().length);
  if(matches.length!==1||matches[0].disabled||matches[0].readOnly)throw Error('Поле '+binding.className+' не найдено однозначно или недоступно. Откройте форму покупки.');
  return matches[0];
 }
 function genderOf(group){
  const selected=[...group.querySelectorAll('input[type=radio]')].find(input=>input.checked);
  const label=selected?.closest('.TVInputRadio')?.textContent||'';
  if(/Муж/i.test(label))return 'male';
  if(/Жен/i.test(label))return 'female';
  throw Error('Не удалось определить поле пола туриста.');
 }
 function setInput(binding,value){
  const input=inputFor(binding);
  if(binding.kind==='gender'){
   const radio=[...input.querySelectorAll('input[type=radio]')].find(node=>(value==='male'?/Муж/i:/Жен/i).test(node.closest('.TVInputRadio')?.textContent||''));
   if(!radio||radio.disabled)throw Error('Не найден переключатель пола туриста.');
   if(!radio.checked)radio.click();
   if(genderOf(inputFor(binding))!==value)throw Error('Модуль не принял выбранный пол туриста.');
   return;
  }
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
 function normalizeCountry(value){
  const name=String(value||'').toLowerCase().replace(/[^a-zа-яё0-9]/g,'');
  return ['россия','российскаяфедерация','russia','russianfederation','rus','ru','643'].includes(name)?'ru':name;
 }
 function matchPeople(people,tourists){
  if(people.length!==tourists.length)throw Error('Состав не совпал: в форме '+people.length+', в договоре '+tourists.length+' туристов. Измените состав выбранного тура.');
  const remaining=[...tourists].sort((a,b)=>a.birthday_iso.localeCompare(b.birthday_iso)||a.id-b.id),assigned=[];
  const slots=people.map((node,index)=>{
   const header=node.querySelector('.TVTourBuyTouristItemHeader')?.textContent.trim()||'';
   if(/^Взрослый турист/i.test(header))return {index,header,priority:1,eligible:person=>person.age>=18};
   if(/Реб[её]нок|Младенец/i.test(header)){
    if(/до\s*2\s*лет/i.test(header))return {index,header,priority:2,eligible:person=>person.age>=0&&person.age<2};
    const age=header.match(/\((\d+)\s*(?:лет|год)/i);
    if(age)return {index,header,priority:0,eligible:person=>person.age===Number(age[1])&&person.age<18};
   }
   throw Error('Не распознан возраст блока туриста: '+header);
  });
  // Exact age first, so a flexible under-2 slot cannot consume the only 1-year-old.
  for(const slot of slots.sort((a,b)=>a.priority-b.priority||a.index-b.index)){
   const index=remaining.findIndex(slot.eligible);
   if(index<0)throw Error('В договоре нет подходящего туриста для «'+slot.header+'». Проверьте возраст на начало тура.');
   assigned[slot.index]=remaining.splice(index,1)[0];
  }
  return assigned;
 }
 async function fill(){
  button.disabled=true;
  try{
   if(!await authorize()){panel.remove();return;}
   const response=await fetch(new URL('/booking-prefill/data/',endpoint),{credentials:'include',cache:'no-store',redirect:'error'});
   const data=await response.json();
   if(!response.ok)throw Error([data.error,...(data.issues||[])].join('\n'));
   const people=visible('.TVTourBuyTouristItemControl');
   const assigned=matchPeople(people,data.tourists),warnings=[];
   const bindings=[];
   assigned.forEach((person,index)=>{
    const nationality=people[index].querySelector('.TVTouristNationality input')?.value||'';
    if(person.nationality&&normalizeCountry(person.nationality)!==normalizeCountry(nationality))throw Error('Гражданство туриста '+person.SURNAME+' не совпало с формой. Проверьте его до заполнения.');
    if(!person.document_type)warnings.push(person.SURNAME+': в CRM не указан тип паспорта, проверьте документ');
    if(!person.nationality)warnings.push(person.SURNAME+': гражданство в CRM не указано, в форме останется '+(nationality||'текущее значение'));
    if(person.document_type==='1'&&/Заграничный паспорт/i.test(people[index].textContent))throw Error(person.SURNAME+': в CRM российский паспорт, а в форме нужен заграничный.');
    const surnameLabel=people[index].querySelector('.TVTouristSurname')?.textContent||'';
    if(/латиниц/i.test(surnameLabel)&&!(/^[A-Za-z '\-]+$/.test(person.SURNAME)&&/^[A-Za-z '\-]+$/.test(person.NAME)))throw Error(person.SURNAME+': для этой формы нужны имя и фамилия латиницей по паспорту.');
    for(const [key,className] of Object.entries(touristFields)){
     if(!person[key])warnings.push(person.SURNAME+': не заполнено '+className.replace(/^TV/,''));
     bindings.push({person:index,className,value:person[key]||''});
    }
    bindings.push({person:index,className:'TVTouristGenderBlock',kind:'gender',value:person.gender});
   });
   for(const [key,className] of Object.entries(customerFields))bindings.push({className,value:data.customer[key]||''});
   for(const binding of bindings){
    const node=inputFor(binding);binding.node=node;
    if(binding.kind==='gender'){binding.before=genderOf(node);continue;}
    binding.before=node.value;
    const content=node.value.replace(/[\s_().+\-]/g,'');
    if(content&&(binding.className!=='TVCustomerContactsPhone'||content!=='7'))throw Error('В форме уже есть данные. Они не заменяются. Откройте пустую форму или уберите предыдущее заполнение.');
   }
   const roster=assigned.map((person,index)=>(index+1)+'. '+person.SURNAME+' '+person.NAME+' — '+person.BIRTHDAY+' ('+person.age+' лет)').join('\n');
   if(!window.confirm('Заполнить из договора '+data.contract.number+'?\nНачало тура в договоре: '+data.contract.start+'\nЗаказчик: '+data.customer.Name+'\n\nТуристы в порядке полей формы:\n'+roster+(warnings.length?'\n\nПроверить вручную:\n'+warnings.join('\n'):'')+'\n\nОтправка заявки и оплата выполняются вами отдельно.'))return;
   saved={hash:location.hash,bindings};
   try{
    for(const binding of bindings)setInput(binding,binding.value);
    reset.hidden=false;status.textContent='Заполнено из договора '+data.contract.number+'. Проверьте все поля, гражданство и даты перед бронированием.';
   }catch(error){reset.hidden=false;restore();throw error;}
  }catch(error){status.textContent=error.message||'Не удалось заполнить форму.';}
  finally{button.disabled=false;}
 }
 function diagnostics(){
  const address=value=>{try{const url=new URL(value,location.href);return url.origin+url.pathname}catch{return 'unavailable'}};
  const fields=[...document.querySelectorAll('input,select,textarea')].filter(node=>!panel?.contains(node)&&node.getClientRects().length&&node.type!=='hidden').slice(0,100).map(node=>{
   const parents=[];let parent=node.parentElement;
   for(let depth=0;parent&&depth<5;depth++,parent=parent.parentElement)parents.push({tag:parent.tagName,classes:String(parent.className||'').slice(0,240)});
   return {tag:node.tagName,type:node.type||'',name:node.name||'',id:node.id||'',placeholder:node.getAttribute('placeholder')||'',classes:String(node.className||'').slice(0,240),parents};
  });
  return JSON.stringify({probe_version:5,page:address(location.href),runtime:{TV:typeof window.TV,initTv:typeof window.initTv,keys:Object.keys(window.TV||{}).sort().slice(0,160)},scripts:[...document.scripts].filter(node=>node.src).map(node=>address(node.src)),frames:[...document.querySelectorAll('iframe')].map(node=>address(node.src)),fields},null,2);
 }
 function show(){
  if(!document.querySelector('.tv-moduleid-898'))return;
  panel=document.createElement('aside');panel.setAttribute('aria-label','Тест заполнения из CRM');
  Object.assign(panel.style,{position:'fixed',left:'16px',bottom:'16px',zIndex:'2147483000',maxWidth:'330px',padding:'14px',border:'2px solid #183f35',borderRadius:'10px',background:'#fffbe9',color:'#183f35',font:'14px sans-serif',boxShadow:'0 3px 16px #0003'});
  const title=document.createElement('strong');title.textContent='CRM · заполнение из договора';
  button=document.createElement('button');button.type='button';button.textContent='Заполнить из договора';button.onclick=fill;
  status=document.createElement('p');status.setAttribute('role','status');status.textContent='Подготовьте договор в CRM и откройте пустую форму бронирования.';
  reset=document.createElement('button');reset.type='button';reset.textContent='Убрать подставленные данные';reset.hidden=true;
  reset.onclick=restore;
  const diagnosticButton=document.createElement('button');diagnosticButton.type='button';diagnosticButton.textContent='Скопировать диагностику';
  diagnosticButton.onclick=async()=>{
   const text=diagnostics();
   try{await navigator.clipboard.writeText(text);status.textContent='Диагностика скопирована. Пришлите её в чат. Значения полей в отчёт не включены.';}
   catch{const output=document.createElement('textarea');output.readOnly=true;output.value=text;output.rows=8;output.style.width='100%';panel.append(output);output.select();status.textContent='Скопируйте этот отчёт и пришлите в чат.';}
  };
  const choose=document.createElement('a');choose.href=new URL('/booking-prefill/select/',endpoint).href;choose.target='_blank';choose.rel='noopener';choose.textContent='Выбрать договор в CRM';
  panel.append(choose,document.createElement('br'),title,document.createElement('br'),button,status,reset,document.createElement('br'),diagnosticButton);document.body.append(panel);
 }
 async function init(){try{if(await authorize())show();}catch{/* Public visitors see no UI or technical errors. */}}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
