const {test}=require('node:test');const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');const fs=require('node:fs');
test('adding a question keeps unique names, updates management count, and never submits',async()=>{
 const dom=new JSDOM('<form data-unsaved><input id="id_answers-TOTAL_FORMS" value="1"><div id="eta-answer-rows"></div><template id="eta-empty-answer"><label for="id_answers-__prefix__-question">Question</label><input name="answers-__prefix__-question" id="id_answers-__prefix__-question"></template><button type="button" id="eta-add-answer">Add</button></form>',{url:'https://example.invalid/',runScripts:'outside-only'});
 const w=dom.window,d=w.document;let submitted=0;
 d.querySelector('form').addEventListener('submit',event=>{submitted++;event.preventDefault()});
 w.eval(fs.readFileSync('crm/static/crm/contract_card.js','utf8'));w.eval(fs.readFileSync('crm/static/crm/eta_prepare.js','utf8'));
 await new Promise(resolve=>setImmediate(resolve));
 d.querySelector('button').click();d.querySelector('button').click();
 assert.equal(d.getElementById('id_answers-TOTAL_FORMS').value,'3');
 assert.deepEqual([...d.querySelectorAll('#eta-answer-rows input')].map(input=>input.name),['answers-1-question','answers-2-question']);
 assert.equal(d.querySelector('form').dataset.dirty,'1');assert.equal(submitted,0);
 d.getElementById('id_answers-TOTAL_FORMS').value='49';d.querySelector('button').click();
 assert.equal(d.getElementById('id_answers-TOTAL_FORMS').value,'50');assert.equal(d.querySelector('button').disabled,true);
 dom.window.close();
});
