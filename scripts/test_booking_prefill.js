const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync('crm/static/crm/booking_prefill_demo.js','utf8');
async function setup({allowed=true,origin='https://aborigen-tour.ru',existing=false,lateExports=false}={}){
 const panels=[],requests=[];let refreshes=0;
 let tourists=[{Id:1,Age:0,DocumentType:5,NAME:existing?'REAL':'',SURNAME:''},{Id:2,Age:0,DocumentType:5,NAME:'',SURNAME:''}];
 let customer={DocumentType:1,Name:''};
 const before=JSON.stringify({tourists,customer});
 const catalog={getTouristsData:()=>tourists,getCustomerData:()=>customer,setTouristsData:value=>tourists=value,setCustomerData:value=>customer=value};
 function element(tag){return {tag,style:{},children:[],setAttribute(){},append(...items){this.children.push(...items)},remove(){this.removed=true}};}
 const document={currentScript:{src:'https://crm.aborigen-tour.ru/static/crm/booking_prefill_demo.js'},readyState:'complete',querySelector:selector=>selector==='.tv-moduleid-898'?{}:null,createElement:element,body:{append:panel=>panels.push(panel)}};
 const context={document,location:{origin,pathname:'/book/offers_tourv.php',hash:'#tvtourid=123'},URL,Set,JSON,Boolean,Error,window:{TV:{orderCatalog:catalog,orderManager:{_TourId:123,_instance:{_tourBuyForm:{update(){refreshes++;}}}}}},fetch:async(url,options)=>{requests.push(options);return {ok:allowed,json:async()=>({enabled:true,test_only:true,customer:{Name:'TEST CUSTOMER'},tourists:[{NAME:'IVAN',SURNAME:'TESTOV'},{NAME:'PETR',SURNAME:'PROBNY'}]})}}};
 if(lateExports){const runtime=context.window.TV;context.window.TV={};context.window.initTv=()=>context.window.TV=runtime;}
 vm.runInNewContext(source,context);await new Promise(resolve=>setImmediate(resolve));
 return {panels,requests,context,before,getData:()=>JSON.stringify({tourists,customer}),getRefreshes:()=>refreshes};
}
test('public visitor and foreign site never receive a button',async()=>{
 const publicPage=await setup({allowed:false});assert.equal(publicPage.panels.length,0);
 const foreign=await setup({origin:'https://evil.invalid'});assert.equal(foreign.requests.length,0);assert.equal(foreign.panels.length,0);
});
test('authorized click fills model and restores without any form submission',async()=>{
 const page=await setup();assert.equal(page.panels.length,1);assert.equal(page.getData(),page.before);
 const panel=page.panels[0],buttons=panel.children.filter(node=>node.tag==='button');
 await buttons[0].onclick();assert.match(page.getData(),/TEST CUSTOMER/);assert.match(page.getData(),/TESTOV/);assert.equal(page.getRefreshes(),1);
 assert.equal(page.requests.length,2);assert.ok(page.requests.every(options=>options.credentials==='include'&&!options.method));
 buttons[1].onclick();assert.equal(page.getData(),page.before);assert.equal(page.getRefreshes(),2);
});
test('existing personal data is never overwritten',async()=>{
 const page=await setup({existing:true});const fill=page.panels[0].children.find(node=>node.tag==='button');await fill.onclick();assert.equal(page.getData(),page.before);assert.equal(page.getRefreshes(),0);
});
test('restore does not clear a different tour',async()=>{
 const page=await setup();const buttons=page.panels[0].children.filter(node=>node.tag==='button');await buttons[0].onclick();const filled=page.getData();page.context.location.hash='#tvtourid=OTHER';buttons[1].onclick();assert.equal(page.getData(),filled);
});

test('late Tourvisor exports are refreshed before accessing catalog',async()=>{
 const page=await setup({lateExports:true});const fill=page.panels[0].children.find(node=>node.tag==='button');await fill.onclick();assert.match(page.getData(),/TESTOV/);assert.equal(page.getRefreshes(),1);
});
