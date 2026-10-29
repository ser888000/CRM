const {test}=require('node:test');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const source=fs.readFileSync('crm/static/crm/task_done.js','utf8');
const formBehavior=fs.readFileSync('crm/static/crm/contract_card.js','utf8');
for(const initial of ['True','False']){
 test(`task status toggles without submitting and marks edits unsaved (${initial})`,async()=>{
  const dom=new JSDOM(`<form data-unsaved><input type="hidden" name="done" id="id_done" value="${initial}"><button type="button" data-task-done="id_done"></button></form>`,{url:'https://example.invalid/tasks/1/',runScripts:'outside-only'});
  const {window:w}=dom;w.eval(formBehavior);w.eval(source);
  await new Promise(resolve=>setImmediate(resolve));
  const button=w.document.querySelector('button'),input=w.document.querySelector('input'),form=w.document.querySelector('form');
  let submitted=0;form.addEventListener('submit',event=>{submitted++;event.preventDefault()});
  assert.equal(input.value,initial==='True'?'1':'0');
  button.click();assert.equal(input.value,initial==='True'?'0':'1');
  assert.equal(button.getAttribute('aria-pressed'),initial==='True'?'false':'true');
  assert.equal(form.dataset.dirty,'1');assert.equal(submitted,0);
  button.click();assert.equal(input.value,initial==='True'?'1':'0');assert.equal(submitted,0);
  dom.window.close();
 });
}
