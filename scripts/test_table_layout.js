const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const script=fs.readFileSync('crm/static/crm/table_layout.js','utf8');
const pause=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 const dom=new JSDOM('<body data-theme="accounting"><form id="journal-filters"></form><div class="journal-scroll"><table data-layout-key="contracts"><thead><tr><th data-col="number" data-label="Договор" draggable="true">Договор</th><th data-col="amount" data-label="Сумма">Сумма</th></tr><tr class="column-search-row"><th data-col="number"><input></th><th data-col="amount"><input></th></tr></thead><tbody><tr><td data-col="number">1</td><td data-col="amount">100</td></tr></tbody><tfoot><tr><td data-col="number">Итого</td><td data-col="amount">100</td></tr></tfoot></table></div></body>',{url:'https://example.invalid/',runScripts:'outside-only'});
 const calls=[];dom.window.crmInterface={preferences:{column_widths:{contracts:{amount:180}}},save:async value=>calls.push(JSON.parse(JSON.stringify(value)))};
 dom.window.eval(script);return {dom,calls};
}
test('saved widths, pointer/keyboard resizing and reset persist without submitting',async()=>{
 const {dom,calls}=fixture();await pause();const w=dom.window,d=w.document,table=d.querySelector('table'),header=d.querySelector('th[data-col=number]'),handle=header.querySelector('.column-resize-handle');
 assert.equal(d.querySelector('col[data-col=amount]').style.width,'180px');
 handle.dispatchEvent(new w.KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true,cancelable:true}));await pause();
 assert.deepEqual(calls[0],{table:'contracts',widths:{number:108}});
 header.getBoundingClientRect=()=>({width:108});
 handle.dispatchEvent(new w.MouseEvent('pointerdown',{button:0,clientX:100,bubbles:true,cancelable:true}));assert.equal(header.draggable,false);
 d.dispatchEvent(new w.MouseEvent('pointermove',{clientX:150,bubbles:true}));d.dispatchEvent(new w.MouseEvent('pointerup',{clientX:150,bubbles:true}));await pause();
 assert.equal(header.draggable,true);assert.equal(d.querySelector('col[data-col=number]').style.width,'158px');assert.deepEqual(calls[1],{table:'contracts',widths:{number:158}});
 d.querySelector('.reset-column-widths').click();await pause();assert.deepEqual(calls[2],{table:'contracts',widths:null});assert.equal(d.querySelector('col[data-col=number]').style.width,'100px');dom.window.close();
});
test('column geometry follows reorder/hiding and leaves footer cells intact',async()=>{
 const {dom}=fixture();await pause();const w=dom.window,d=w.document,table=d.querySelector('table');
 [...table.rows].forEach(row=>row.prepend(row.querySelector('[data-col=amount]')));table.dispatchEvent(new w.Event('crm:columns'));
 assert.deepEqual([...table.querySelectorAll('col')].map(c=>c.dataset.col),['amount','number']);
 d.querySelector('th[data-col=amount]').hidden=true;table.dispatchEvent(new w.Event('crm:columns'));assert.equal(d.querySelector('col[data-col=amount]').hidden,true);
 assert.equal(table.tFoot.querySelector('[data-col=amount]').textContent,'100');assert.equal(d.querySelectorAll('.column-search-row input').length,2);dom.window.close();
});
