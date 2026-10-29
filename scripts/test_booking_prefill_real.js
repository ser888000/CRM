/* DOM tests: npm install --prefix /tmp/booking-probe-tools --cache /tmp/booking-npm-cache jsdom
   NODE_PATH=/tmp/booking-probe-tools/node_modules node --test scripts/test_booking_prefill.js */
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const {JSDOM}=require('jsdom');
const source=fs.readFileSync('crm/static/crm/booking_prefill.js','utf8');
const touristClasses=['TVTouristSurname','TVTouristName','TVTouristBirthday','TVPassportNumber','TVPassportIssue','TVPassportExpiry','TVPassportAuthority'];
const customerClasses=['TVCustomerContactsName','TVCustomerContactsPhone','TVCustomerContactsEmail','TVCustomerContactsAddress','TVCustomerContactsBirthday','TVCustomerContactsPassportNumber','TVCustomerContactsPassportIssue','TVCustomerContactsPassportAuthority','TVCustomerContactsPassportAuthorityCode'];
const example={enabled:true,test_only:false,contract:{number:'TEST',start:'2026-12-24'},customer:{Name:'TEST CUSTOMER',Phone:'+79990000000',Email:'test@example.invalid',Address:'TEST ADDRESS',Birthday:'01.01.1980',PassportNumber:'0000 000001',PassportIssue:'01.01.2020',PassportAuthority:'TEST',PassportAuthorityCode:'000-000'},tourists:[{id:1,age:46,birthday_iso:'1980-01-01',gender:'male',nationality:'Россия',document_type:'0',NAME:'IVAN',SURNAME:'TESTOV',BIRTHDAY:'01.01.1980',PASSPORTNUMBER:'00 0000001',PASSPORTISSUE:'01.01.2020',PASSPORTEXPIRY:'01.01.2030',PASSPORTAUTHORITY:'TEST'},{id:2,age:44,birthday_iso:'1982-02-02',gender:'female',nationality:'Россия',document_type:'0',NAME:'PETR',SURNAME:'PROBNY',BIRTHDAY:'02.02.1980',PASSPORTNUMBER:'00 0000002',PASSPORTISSUE:'01.01.2020',PASSPORTEXPIRY:'01.01.2030',PASSPORTAUTHORITY:'TEST'}]};
async function setup({allowed=true,origin='https://aborigen-tour.ru',existing=false,missing=false,headers=['Взрослый турист 1','Взрослый турист 2'],tourists=null,confirm=true}={}){
 const field=cls=>`<div class="${cls}"><input type="text"></div>`;
 let personIndex=0;
 const person=header=>`<section class="TVTourBuyTouristItemControl"><header class="TVTourBuyTouristItemHeader">${header}</header><div class="TVTouristGenderBlock"><div class="TVInputRadio"><input type="radio" name="gender-${personIndex}" checked>Муж</div><div class="TVInputRadio"><input type="radio" name="gender-${personIndex++}">Жен</div></div><div class="TVTouristNationality"><input value="Россия" readonly></div>${touristClasses.map(field).join('')}</section>`;
 const dom=new JSDOM(`<div class="tv-moduleid-898"></div><input id="unrelated" value="UNCHANGED"><input type="checkbox" id="consent">${headers.map(person).join('')}${customerClasses.map(field).join('')}`,{url:origin+'/book/offers_tourv.php#tvtourid=123',runScripts:'outside-only'});
 const w=dom.window,d=w.document;let copied='';const requests=[],model=new Map();
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 Object.defineProperty(w.HTMLElement.prototype,'getClientRects',{value(){return this.hidden?[]:[{width:100,height:25}]}});
 Object.defineProperty(d,'readyState',{value:'complete'});
 const script=d.createElement('script');script.src='https://crm.aborigen-tour.ru/static/crm/booking_prefill.js?v=6';d.body.append(script);
 Object.defineProperty(d,'currentScript',{value:script});
 const vendor=d.createElement('script');vendor.src='https://tourvisor.ru/module/init.js?authkey=SECRET';d.body.append(vendor);
 if(existing)d.querySelector('.TVTouristSurname input').value='REAL EXISTING DATA';
 if(missing)d.querySelector('.TVCustomerContactsAddress').remove();
 d.querySelectorAll('input').forEach(input=>input.addEventListener('input',()=>model.set(input,input.value)));
 w.TV={getRequestId(){},loadModules(){}}; // Actual site's public API has no orderCatalog/initTv.
 const payload={...example,tourists:tourists||example.tourists};
 w.fetch=async(url,options)=>{requests.push(options);return {ok:allowed,json:async()=>String(url).includes('/data/')?payload:{enabled:true,contract:{number:'TEST'}}}};w.confirm=()=>confirm;
 Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied=text}});
 w.HTMLFormElement.prototype.submit=()=>{throw Error('Must not submit')};const nativeClick=w.HTMLElement.prototype.click;w.HTMLElement.prototype.click=function(){if(this.tagName!=='INPUT'||this.type!=='radio')throw Error('Must not click booking controls');return nativeClick.call(this)};
 w.eval(source);await new Promise(resolve=>setImmediate(resolve));
 const dateField=d.querySelector('aside input[type=date]');if(dateField)dateField.value='2026-12-24';
 const panel=d.querySelector('aside'),buttons=panel?[...panel.querySelectorAll('button')]:[];
 return {w,d,panel,buttons,requests,model,getCopied:()=>copied};
}

test('real data fills fields, changes gender, leaves consent and unrelated fields untouched',async()=>{
 const page=await setup();await page.buttons[0].onclick();
 assert.equal(page.d.querySelector('.TVTouristSurname input').value,'TESTOV');
 const groups=page.d.querySelectorAll('.TVTouristGenderBlock');assert.equal(groups[1].querySelectorAll('input')[1].checked,true);
 assert.equal(page.d.querySelector('#consent').checked,false);assert.equal(page.d.querySelector('#unrelated').value,'UNCHANGED');
 page.buttons[1].onclick();assert.equal(groups[1].querySelectorAll('input')[0].checked,true);assert.equal(page.d.querySelector('.TVTouristSurname input').value,'');
});
function traveler(id,age,birthday,surname){return {...example.tourists[0],id,age,birthday_iso:birthday,SURNAME:surname};}
test('six travelers: adults sorted oldest first, children matched to displayed ages',async()=>{
 const people=[traveler(1,30,'1996-01-01','ADULTB'),traveler(2,6,'2020-01-01','CHILDSIX'),traveler(3,50,'1976-01-01','ADULTA'),traveler(4,20,'2006-01-01','ADULTD'),traveler(5,10,'2016-01-01','CHILDTEN'),traveler(6,25,'2001-01-01','ADULTC')];
 const page=await setup({tourists:people,headers:['Взрослый турист 1','Взрослый турист 2','Взрослый турист 3','Взрослый турист 4','Ребенок 1 (6 лет)','Ребенок 2 (10 лет)']});await page.buttons[0].onclick();
 assert.deepEqual([...page.d.querySelectorAll('.TVTouristSurname input')].map(n=>n.value),['ADULTA','ADULTB','ADULTC','ADULTD','CHILDSIX','CHILDTEN']);
});
test('exact one-year slot is matched before a flexible under-2 slot',async()=>{
 const page=await setup({tourists:[traveler(1,0,'2026-02-01','INFANT'),traveler(2,1,'2025-01-01','ONEYEAR')],headers:['Ребенок 1 (до 2 лет)','Ребенок 2 (1 год)']});await page.buttons[0].onclick();
 assert.deepEqual([...page.d.querySelectorAll('.TVTouristSurname input')].map(n=>n.value),['INFANT','ONEYEAR']);
});
test('unmatched child slots remain blank while suitable adults are filled',async()=>{
 const page=await setup({tourists:[example.tourists[0],traveler(3,9,'2017-01-01','CHILDNINE')],headers:['Взрослый турист','Ребенок 1 (6 лет)']});await page.buttons[0].onclick();
 const names=page.d.querySelectorAll('.TVTouristSurname input');assert.equal(names[0].value,'TESTOV');assert.equal(names[1].value,'');
});
test('real values already entered are never overwritten',async()=>{
 const page=await setup({existing:true});await page.buttons[0].onclick();assert.equal(page.model.size,0);
});

test('surplus adults prompt selection and cancellation writes nothing',async()=>{
 const page=await setup({tourists:[...example.tourists,traveler(3,30,'1996-01-01','EXTRA')]});
 const pending=page.buttons[0].onclick();await new Promise(resolve=>setImmediate(resolve));
 const dialog=page.d.querySelector('dialog');assert.ok(dialog);
 dialog.querySelectorAll('button')[1].onclick();await pending;assert.equal(page.model.size,0);
});
test('surplus adult can be chosen explicitly instead of the oldest',async()=>{
 const page=await setup({tourists:[...example.tourists,traveler(3,30,'1996-01-01','EXTRA')]});
 const pending=page.buttons[0].onclick();await new Promise(resolve=>setImmediate(resolve));
 const dialog=page.d.querySelector('dialog'),selects=dialog.querySelectorAll('select');selects[0].value='3';selects[1].value='3';dialog.querySelector('button').onclick();assert.equal(page.model.size,0);assert.ok(dialog.open);selects[1].value='2';dialog.querySelector('button').onclick();await pending;
 assert.deepEqual([...page.d.querySelectorAll('.TVTouristSurname input')].map(n=>n.value),['EXTRA','PROBNY']);
});
test('missing tourists leave extra adult and child fields blank',async()=>{
 const page=await setup({tourists:[example.tourists[0]],headers:['Взрослый турист 1','Взрослый турист 2','Ребенок 1 (6 лет)']});await page.buttons[0].onclick();
 assert.deepEqual([...page.d.querySelectorAll('.TVTouristSurname input')].map(n=>n.value),['TESTOV','','']);
 assert.equal(page.d.querySelector('.TVCustomerContactsName input').value,'TEST CUSTOMER');
});

test('extra children of the same age can be selected by name',async()=>{
 const page=await setup({tourists:[example.tourists[0],traveler(3,6,'2020-01-01','CHILDA'),traveler(4,6,'2020-06-01','CHILDB')],headers:['Взрослый турист','Ребенок 1 (6 лет)']});
 const pending=page.buttons[0].onclick();await new Promise(resolve=>setImmediate(resolve));
 const dialog=page.d.querySelector('dialog');dialog.querySelectorAll('select')[1].value='4';dialog.querySelector('button').onclick();await pending;
 assert.deepEqual([...page.d.querySelectorAll('.TVTouristSurname input')].map(n=>n.value),['TESTOV','CHILDB']);
});

test('clear carried data after another tour renders, preserving manual edits and unrelated tourists',async()=>{
 const page=await setup();await page.buttons[0].onclick();
 for(const root of [...page.d.querySelectorAll('.TVTourBuyTouristItemControl')]){
  const clone=root.cloneNode(true);root.querySelectorAll('input').forEach((input,index)=>clone.querySelectorAll('input')[index].value=input.value);root.replaceWith(clone);
 }
 page.w.history.replaceState({},'', '#tvtourid=456');
 page.d.querySelector('.TVPassportAuthority input').value='MANUAL EDIT';
 page.buttons[1].onclick();
 assert.equal(page.d.querySelector('.TVTouristSurname input').value,'');
 assert.equal(page.d.querySelector('.TVPassportAuthority input').value,'MANUAL EDIT');
 assert.equal(page.d.querySelector('.TVCustomerContactsName input').value,'');
 assert.equal(page.d.querySelector('#unrelated').value,'UNCHANGED');
 assert.equal(page.buttons.length,3);
});
test('tour card supplies date automatically, including explicit year and current-year omission',async()=>{
 const page=await setup();
 const card=page.d.createElement('div');card.className='TVTourCardInfoControl';card.innerHTML='<div class="TVTourCardOption"><i class="TVCalendarIcon"></i><span class="TVTourCardOptionHeader">5 ноября 2027</span></div>';page.d.body.append(card);
 await new Promise(resolve=>setImmediate(resolve));
 const date=page.panel.querySelector('input[type=date]');assert.equal(date.value,'2027-11-05');assert.equal(date.readOnly,true);
 card.querySelector('span').textContent='5 ноября';await new Promise(resolve=>setImmediate(resolve));
 assert.equal(date.value,`${new Date().getFullYear()}-11-05`);
 card.querySelector('span').textContent='31 февраля 2027';await new Promise(resolve=>setImmediate(resolve));assert.equal(date.readOnly,false);
});


test('date stays out of view and helper can collapse and reopen',async()=>{
 const page=await setup();
 assert.equal(page.panel.querySelector('label').hidden,true);
 page.buttons[2].onclick();assert.equal(page.panel.hidden,true);
 assert.equal(page.w.sessionStorage.getItem('aborigen-crm-prefill-collapsed'),'1');
 const launcher=page.d.querySelector('button[aria-label="Открыть помощник CRM"]');
 assert.equal(launcher.hidden,false);launcher.onclick();
 assert.equal(page.panel.hidden,false);assert.equal(launcher.hidden,true);
});
test('manual date appears only when automatic date and manual value are missing',async()=>{
 const page=await setup();page.panel.querySelector('input[type=date]').value='';
 await page.buttons[0].onclick();assert.equal(page.panel.querySelector('label').hidden,false);
 assert.equal(page.model.size,0);
});
