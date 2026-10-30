const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
test('double click opens only the clicked contract and leaves interactive controls alone',async()=>{
 const dom=new JSDOM('<table><thead><tr><th>Header</th></tr></thead><tbody><tr data-open-row><td><a data-row-link href="/contracts/1/">1</a></td><td id="plain">Text</td><td><a id="customer" href="#">Customer</a><button id="status">Paid</button><input id="input"></td></tr></tbody><tfoot><tr><td id="total">Total</td></tr></tfoot></table>',{url:'https://example.invalid/',runScripts:'outside-only'});
 const w=dom.window;w.eval(fs.readFileSync('crm/static/crm/row_open.js','utf8'));await new Promise(resolve=>setImmediate(resolve));
 let opens=0;w.document.querySelector('[data-row-link]').addEventListener('click',e=>{e.preventDefault();opens++});
 function dbl(id,options={}){w.document.getElementById(id).dispatchEvent(new w.MouseEvent('dblclick',{button:0,bubbles:true,cancelable:true,...options}))}
 dbl('plain');assert.equal(opens,1);
 for(const id of ['customer','status','input','total'])dbl(id);
 dbl('plain',{ctrlKey:true});assert.equal(opens,1);dom.window.close();
});
