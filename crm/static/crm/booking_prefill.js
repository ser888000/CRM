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
 let saved=null,panel,button,status,reset,startDate,sourceLabel,dateLabel;
 async function authorize(){
  const response=await fetch(endpoint,{credentials:'include',cache:'no-store',redirect:'error'});
  if(!response.ok)return null;
  const data=await response.json();return data.enabled?data:null;
 }
 const touristFields={SURNAME:'TVTouristSurname',NAME:'TVTouristName',BIRTHDAY:'TVTouristBirthday',PASSPORTNUMBER:'TVPassportNumber',PASSPORTISSUE:'TVPassportIssue',PASSPORTEXPIRY:'TVPassportExpiry',PASSPORTAUTHORITY:'TVPassportAuthority'};
 const fieldLabels={SURNAME:'фамилия',NAME:'имя',BIRTHDAY:'дата рождения',PASSPORTNUMBER:'серия и номер паспорта',PASSPORTISSUE:'дата выдачи паспорта',PASSPORTEXPIRY:'срок действия паспорта',PASSPORTAUTHORITY:'кем выдан паспорт'};
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
  try{

   // Tourvisor carries its model into a newly rendered tour. Match each value,
   // rather than trusting old nodes or requiring the old tour's hash.
   const people=visible('.TVTourBuyTouristItemControl');
   const targets=new Map();
   for(const index of new Set(saved.bindings.map(item=>item.person).filter(item=>item!==undefined))){
    const identity=saved.bindings.filter(item=>item.person===index&&['TVTouristSurname','TVTouristName','TVTouristBirthday','TVPassportNumber'].includes(item.className)&&item.written);
    targets.set(index,people.map((root,person)=>({root,person})).filter(({root})=>identity.filter(item=>root.querySelector('.'+item.className+' input')?.value===item.written).length>=2).map(item=>item.person));
   }
   for(const binding of saved.bindings){
    if(binding.kind==='gender')continue;
    const indices=binding.person===undefined?[undefined]:(targets.get(binding.person)||[]);
    for(const person of indices){
     const current={...binding,person};
     let node;try{node=inputFor(current)}catch{continue;}
     if(!binding.written||node.value!==binding.written)continue;
     // Only fields containing values actually written by this helper are cleared.
     setInput(current,binding.before);
    }
   }
   for(const binding of saved.bindings.filter(item=>item.kind==='gender')){
    // Restore gender only on the original group; a new tour has its own default.
    try{if(inputFor(binding)===binding.node&&genderOf(binding.node)===binding.value)setInput(binding,binding.before)}catch{}
   }
   if(!people.length)throw Error('Откройте форму бронирования, чтобы убрать подставленные данные.');
   saved=null;reset.hidden=true;status.textContent='Подставленные данные убраны. Ручные изменения сохранены.';
  }catch(error){status.textContent=error.message;}
 }
 function readTourDate(){
  const months=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  const dates=new Set();
  for(const icon of visible('.TVTourCardInfoControl .TVCalendarIcon')){
   const text=icon.closest('.TVTourCardOption')?.querySelector('.TVTourCardOptionHeader')?.textContent.trim().toLowerCase()||'';
   const match=text.match(/^(\d{1,2})\s+([а-яё]+)(?:\s+(\d{4}))?$/);
   if(!match)continue;
   const month=months.indexOf(match[2]),day=Number(match[1]);
   // Tourvisor getDateNightOptionSettings omits year ONLY for the current year.
   const year=Number(match[3]||new Date().getFullYear());
   const date=new Date(year,month,day);
   if(month>=0&&date.getFullYear()===year&&date.getMonth()===month&&date.getDate()===day)dates.add(`${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`);
  }
  return dates.size===1?[...dates][0]:'';
 }
 function updateTourDate(){
  if(!startDate)return;
  const date=readTourDate();
  if(date){dateLabel.hidden=true;startDate.value=date;startDate.readOnly=true;startDate.title='Дата выбранного тура из Турвизора';}
  else{if(startDate.readOnly)startDate.value='';startDate.readOnly=false;startDate.title='Если дата тура не распознана, укажите её вручную';}
 }
 function normalizeCountry(value){
  const name=String(value||'').toLowerCase().replace(/[^a-zа-яё0-9]/g,'');
  return ['россия','российскаяфедерация','russia','russianfederation','rus','ru','643'].includes(name)?'ru':name;
 }
 function makePlan(people,tourists){
  if(!people.length)throw Error('Откройте форму бронирования тура.');
  const candidates=[...tourists].filter(person=>Number.isInteger(person.age)&&person.age>=0&&!(person.issues||[]).length).sort((a,b)=>a.birthday_iso.localeCompare(b.birthday_iso)||a.id-b.id);
  const remaining=[...candidates],assigned=Array(people.length).fill(null);
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
  for(const slot of [...slots].sort((a,b)=>a.priority-b.priority||a.index-b.index)){
   const index=remaining.findIndex(slot.eligible);
   if(index>=0)assigned[slot.index]=remaining.splice(index,1)[0];
  }
  const extra=remaining.some(person=>slots.some(slot=>slot.eligible(person)));
  return {slots,candidates,assigned,extra};
 }
 function choosePeople(plan,data){
  return new Promise(resolve=>{
   const dialog=document.createElement('dialog');dialog.className='aborigen-prefill-choice';
   Object.assign(dialog.style,{maxWidth:'650px',width:'90vw',maxHeight:'80vh',overflow:'auto',padding:'24px',borderRadius:'12px',border:'1px solid #183f35',font:'15px sans-serif'});
   const title=document.createElement('h3');title.textContent='Кого перенести из договора '+data.contract.number+'?';
   const hint=document.createElement('p');hint.textContent='Выберите нужных туристов. Пустые места можно заполнить вручную. Возраст рассчитан на '+data.contract.start+'.';
   dialog.append(title,hint);const selects=[];
   for(const slot of plan.slots){
    const label=document.createElement('label');label.textContent=slot.header;label.style.display='block';label.style.marginBottom='14px';
    const select=document.createElement('select');select.style.width='100%';select.append(new Option('Оставить пустым — введу вручную',''));
    for(const person of plan.candidates.filter(slot.eligible))select.append(new Option(person.SURNAME+' '+person.NAME+' · '+person.BIRTHDAY+' · '+person.age+' лет',String(person.id)));
    select.value=String(plan.assigned[slot.index]?.id||'');label.append(select);dialog.append(label);selects.push(select);
   }
   const error=document.createElement('p');error.setAttribute('role','alert');dialog.append(error);
   const apply=document.createElement('button');apply.type='button';apply.textContent='Заполнить выбранных';
   const cancel=document.createElement('button');cancel.type='button';cancel.textContent='Отмена';cancel.style.marginLeft='12px';
   function finish(result){dialog.close();dialog.remove();resolve(result);}
   apply.onclick=()=>{const ids=selects.map(select=>select.value),chosen=ids.filter(Boolean);if(new Set(chosen).size!==chosen.length){error.textContent='Один турист выбран несколько раз. Выберите разных или оставьте место пустым.';return;}finish(ids.map(id=>plan.candidates.find(person=>String(person.id)===id)||null));};
   cancel.onclick=()=>finish(null);dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null)});
   dialog.append(apply,cancel);document.body.append(dialog);dialog.showModal();
  });
 }
 async function fill(){
  button.disabled=true;
  try{
   const auth=await authorize();if(!auth){panel.remove();return;}
   sourceLabel.textContent=auth.contract?'Источник: договор '+auth.contract.number:'Сначала нажмите «Данные в Турвизор» в нужном договоре CRM.';
   updateTourDate();
   if(!startDate.value){dateLabel.hidden=false;throw Error('Не удалось прочитать дату тура. Укажите начало поездки вручную.');}
   const dataUrl=new URL('/booking-prefill/data/',endpoint);dataUrl.searchParams.set('start',startDate.value);
   const response=await fetch(dataUrl,{credentials:'include',cache:'no-store',redirect:'error'});
   const data=await response.json();
   if(!response.ok)throw Error([data.error,...(data.issues||[])].join('\n'));
   const formHash=location.hash;
   const people=visible('.TVTourBuyTouristItemControl');
   const plan=makePlan(people,data.tourists),warnings=[];
   const assigned=plan.extra?await choosePeople(plan,data):plan.assigned;
   if(!assigned)return;
   if(formHash!==location.hash||startDate.value!==data.contract.start||visible('.TVTourBuyTouristItemControl').length!==people.length||people.some((node,index)=>visible('.TVTourBuyTouristItemControl')[index]!==node))throw Error('Форма или дата тура изменились. Повторите заполнение.');
   const bindings=[];
   assigned.forEach((person,index)=>{
    if(!person)return;
    const nationality=people[index].querySelector('.TVTouristNationality input')?.value||'';
    if(person.nationality&&normalizeCountry(person.nationality)!==normalizeCountry(nationality)){warnings.push(person.SURNAME+': гражданство не совпало с формой, введите туриста вручную');assigned[index]=null;return;}
    if(!person.document_type)warnings.push(person.SURNAME+': в CRM не указан тип паспорта, проверьте документ');
    if(!person.nationality)warnings.push(person.SURNAME+': гражданство в CRM не указано, в форме останется '+(nationality||'текущее значение'));
    if(person.document_type==='1'&&/Заграничный паспорт/i.test(people[index].textContent)){warnings.push(person.SURNAME+': нужен загранпаспорт, введите туриста вручную');assigned[index]=null;return;}
    const surnameLabel=people[index].querySelector('.TVTouristSurname')?.textContent||'';
    if(/латиниц/i.test(surnameLabel)&&!(/^[A-Za-z '\-]+$/.test(person.SURNAME)&&/^[A-Za-z '\-]+$/.test(person.NAME))){warnings.push(person.SURNAME+': нужны имя и фамилия латиницей, введите туриста вручную');assigned[index]=null;return;}
    for(const [key,className] of Object.entries(touristFields)){
     if(!person[key])warnings.push(person.SURNAME+': не заполнено '+fieldLabels[key]);
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
   saved={hash:location.hash,bindings};
   try{
    for(const binding of bindings){setInput(binding,binding.value);binding.written=binding.kind==='gender'?binding.value:inputFor(binding).value;}
    reset.hidden=false;const empty=assigned.map((person,index)=>person?null:plan.slots[index].header).filter(Boolean);
    const unused=data.tourists.filter(person=>!assigned.some(item=>item?.id===person.id));
    const issues=unused.flatMap(person=>person.issues||[]);
    status.textContent='Заполнено из договора '+data.contract.number+'.'+(empty.length?' Введите вручную: '+empty.join(', ')+'.':'')+(unused.length?' Не перенесено из старого состава: '+unused.length+'.':'')+' Проверьте поля перед бронированием.'+(warnings.length?' '+warnings.join('; '):'')+(issues.length?' '+issues.join('; '):'');
   }catch(error){reset.hidden=false;restore();throw error;}
  }catch(error){status.textContent=error.message||'Не удалось заполнить форму.';}
  finally{button.disabled=false;}
 }
 function show(auth){
  if(!document.querySelector('.tv-moduleid-898'))return;
  panel=document.createElement('aside');panel.setAttribute('aria-label','Тест заполнения из CRM');
  Object.assign(panel.style,{position:'fixed',left:'16px',bottom:'16px',zIndex:'2147483000',maxWidth:'330px',maxHeight:'60vh',overflow:'auto',padding:'14px',border:'2px solid #183f35',borderRadius:'10px',background:'#fffbe9',color:'#183f35',font:'14px sans-serif',boxShadow:'0 3px 16px #0003'});
  const title=document.createElement('strong');title.textContent='CRM · заполнение из договора';
  button=document.createElement('button');button.type='button';button.textContent='Заполнить из договора';button.onclick=fill;
  status=document.createElement('p');status.setAttribute('role','status');status.textContent='Откройте форму тура. Недостающих туристов можно ввести вручную.';
  reset=document.createElement('button');reset.type='button';reset.textContent='Убрать подставленные данные';reset.hidden=true;
  reset.onclick=restore;
  sourceLabel=document.createElement('p');sourceLabel.textContent=auth.contract?'Источник: договор '+auth.contract.number:'Нажмите «Данные в Турвизор» в исходном договоре CRM.';
  dateLabel=document.createElement('label');dateLabel.textContent='Начало новой поездки';dateLabel.hidden=true;startDate=document.createElement('input');startDate.type='date';dateLabel.append(startDate);
  const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Свернуть помощник CRM');
  Object.assign(close.style,{float:'right',marginLeft:'12px',cursor:'pointer'});
  const launcher=document.createElement('button');launcher.type='button';launcher.textContent='CRM';launcher.setAttribute('aria-label','Открыть помощник CRM');
  Object.assign(launcher.style,{position:'fixed',left:'16px',bottom:'16px',zIndex:'2147483000',padding:'8px 12px',border:'1px solid #183f35',borderRadius:'8px',background:'#fffbe9',color:'#183f35',cursor:'pointer'});
  function collapse(value){
   panel.hidden=value;launcher.hidden=!value;
   try{sessionStorage.setItem('aborigen-crm-prefill-collapsed',value?'1':'0')}catch{}
  }
  close.onclick=()=>collapse(true);launcher.onclick=()=>collapse(false);
  panel.append(title,sourceLabel,dateLabel,document.createElement('br'),button,status,reset,close);document.body.append(panel,launcher);
  let collapsed=false;try{collapsed=sessionStorage.getItem('aborigen-crm-prefill-collapsed')==='1'}catch{}
  collapse(collapsed);updateTourDate();
  const observer=new MutationObserver(()=>updateTourDate());
  observer.observe(document.querySelector('.tv-moduleid-898').parentElement,{childList:true,subtree:true,characterData:true});
 }
 window.addEventListener('hashchange',()=>{if(startDate){startDate.value='';startDate.readOnly=false;status.textContent='Выбран другой тур. Дата будет прочитана из его формы.';updateTourDate();}});
 async function init(){try{const auth=await authorize();if(auth)show(auth);}catch{/* Public visitors see no UI or technical errors. */}}
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
