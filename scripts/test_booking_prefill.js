/* DOM tests: npm install --prefix /tmp/booking-probe-tools --cache /tmp/booking-npm-cache jsdom
   NODE_PATH=/tmp/booking-probe-tools/node_modules node --test scripts/test_booking_prefill.js */
const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs');const {JSDOM}=require('jsdom');
const source=fs.readFileSync('crm/static/crm/booking_prefill_demo.js','utf8');
const touristClasses=['TVTouristSurname','TVTouristName','TVTouristBirthday','TVPassportNumber','TVPassportIssue','TVPassportExpiry','TVPassportAuthority'];
const customerClasses=['TVCustomerContactsName','TVCustomerContactsPhone','TVCustomerContactsEmail','TVCustomerContactsAddress','TVCustomerContactsBirthday','TVCustomerContactsPassportNumber','TVCustomerContactsPassportIssue','TVCustomerContactsPassportAuthority','TVCustomerContactsPassportAuthorityCode'];
const example={enabled:true,test_only:true,customer:{Name:'TEST CUSTOMER',Phone:'+79990000000',Email:'test@example.invalid',Address:'TEST ADDRESS',Birthday:'01.01.1980',PassportNumber:'0000 000001',PassportIssue:'01.01.2020',PassportAuthority:'TEST',PassportAuthorityCode:'000-000'},tourists:[{NAME:'IVAN',SURNAME:'TESTOV',BIRTHDAY:'01.01.1980',PASSPORTNUMBER:'00 0000001',PASSPORTISSUE:'01.01.2020',PASSPORTEXPIRY:'01.01.2030',PASSPORTAUTHORITY:'TEST'},{NAME:'PETR',SURNAME:'PROBNY',BIRTHDAY:'02.02.1980',PASSPORTNUMBER:'00 0000002',PASSPORTISSUE:'01.01.2020',PASSPORTEXPIRY:'01.01.2030',PASSPORTAUTHORITY:'TEST'}]};
async function setup({allowed=true,origin='https://aborigen-tour.ru',existing=false,missing=false}={}){
 const field=cls=>`<div class="${cls}"><input type="text"></div>`;
 const person=()=>`<section class="TVTourBuyTouristItemControl"><header class="TVTourBuyTouristItemHeader">Взрослый турист</header>${touristClasses.map(field).join('')}</section>`;
 const dom=new JSDOM(`<div class="tv-moduleid-898"></div><input id="unrelated" value="UNCHANGED">${person()}${person()}${customerClasses.map(field).join('')}`,{url:origin+'/book/offers_tourv.php#tvtourid=123',runScripts:'outside-only'});
 const w=dom.window,d=w.document;let copied='';const requests=[],model=new Map();
 Object.defineProperty(w.HTMLElement.prototype,'getClientRects',{value(){return this.hidden?[]:[{width:100,height:25}]}});
 Object.defineProperty(d,'readyState',{value:'complete'});
 const script=d.createElement('script');script.src='https://crm.aborigen-tour.ru/static/crm/booking_prefill_demo.js?v=4';d.body.append(script);
 Object.defineProperty(d,'currentScript',{value:script});
 const vendor=d.createElement('script');vendor.src='https://tourvisor.ru/module/init.js?authkey=SECRET';d.body.append(vendor);
 if(existing)d.querySelector('.TVTouristSurname input').value='REAL EXISTING DATA';
 if(missing)d.querySelector('.TVCustomerContactsAddress').remove();
 d.querySelectorAll('input').forEach(input=>input.addEventListener('input',()=>model.set(input,input.value)));
 w.TV={getRequestId(){},loadModules(){}}; // Actual site's public API has no orderCatalog/initTv.
 w.fetch=async(url,options)=>{requests.push(options);return {ok:allowed,json:async()=>example}};
 Object.defineProperty(w.navigator,'clipboard',{value:{writeText:async text=>copied=text}});
 w.HTMLFormElement.prototype.submit=()=>{throw Error('Must not submit')};w.HTMLElement.prototype.click=()=>{throw Error('Must not click module controls')};
 w.eval(source);await new Promise(resolve=>setImmediate(resolve));
 const panel=d.querySelector('aside'),buttons=panel?[...panel.querySelectorAll('button')]:[];
 return {w,d,panel,buttons,requests,model,getCopied:()=>copied};
}
test('public visitor and foreign site never receive a button',async()=>{
 const visitor=await setup({allowed:false});assert.equal(visitor.panel,null);
 const foreign=await setup({origin:'https://evil.invalid'});assert.equal(foreign.requests.length,0);assert.equal(foreign.panel,null);
});
test('actual DOM fills without private TV API and input events update model',async()=>{
 const page=await setup();assert.equal(page.model.size,0);
 await page.buttons[0].onclick();
 assert.equal(page.d.querySelector('.TVTouristSurname input').value,'TESTOV');
 assert.equal(page.d.querySelector('.TVCustomerContactsName input').value,'TEST CUSTOMER');
 assert.equal(page.model.size,23);assert.equal(page.model.get(page.d.querySelector('.TVCustomerContactsEmail input')),'test@example.invalid');
 assert.equal(page.d.querySelector('#unrelated').value,'UNCHANGED');
 assert.equal(page.requests.length,2);assert.ok(page.requests.every(options=>options.credentials==='include'&&!options.method));
 page.buttons[1].onclick();assert.ok([...page.model.values()].every(value=>value===''));
});
test('existing personal data is never overwritten',async()=>{
 const page=await setup({existing:true});await page.buttons[0].onclick();assert.equal(page.model.size,0);assert.equal(page.d.querySelector('.TVTouristSurname input').value,'REAL EXISTING DATA');
});
test('missing field prevents partial fill',async()=>{
 const page=await setup({missing:true});await page.buttons[0].onclick();assert.equal(page.model.size,0);
});
test('restore does not clear another tour or a reopened form',async()=>{
 const page=await setup();await page.buttons[0].onclick();page.w.location.hash='#tvtourid=OTHER';page.buttons[1].onclick();assert.equal(page.d.querySelector('.TVTouristSurname input').value,'TESTOV');
 const reopened=await setup();await reopened.buttons[0].onclick();const node=reopened.d.querySelector('.TVTouristSurname input');node.replaceWith(node.cloneNode());reopened.buttons[1].onclick();assert.equal(reopened.d.querySelector('.TVTouristSurname input').value,'TESTOV');
});
test('diagnostics never reads field values or URL secrets',async()=>{
 const page=await setup();page.d.querySelectorAll('input').forEach(input=>Object.defineProperty(input,'value',{get(){throw Error('Do not read personal value')}}));
 await page.buttons[2].onclick();const output=page.getCopied();assert.match(output,/TVTouristSurname/);assert.doesNotMatch(output,/SECRET|authkey|UNCHANGED/);assert.equal(JSON.parse(output).probe_version,4);
});
