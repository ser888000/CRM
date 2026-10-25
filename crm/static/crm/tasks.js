document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('#id_start,#id_end').forEach(input=>input.addEventListener('change',()=>document.querySelector('#task-period').value='custom'));
 const form=document.querySelector('#task-actions');if(!form)return;
 const all=document.querySelector('#tasks-select-all'),boxes=[...form.querySelectorAll('[name=tasks]')],counter=document.querySelector('#task-selected-count'),action=document.querySelector('#task-action'),date=document.querySelector('#task-bulk-due'),label=document.querySelector('#task-due-label');
 function update(){const count=boxes.filter(b=>b.checked).length;if(counter)counter.textContent=count;if(all){all.checked=!!boxes.length&&count===boxes.length;all.indeterminate=count>0&&count<boxes.length}form.querySelectorAll('.task-bulk button').forEach(button=>button.disabled=!count)}
 all?.addEventListener('change',()=>{boxes.forEach(b=>b.checked=all.checked);update()});boxes.forEach(b=>b.addEventListener('change',update));update();
 function dates(){if(label)label.hidden=action.value!=='reschedule';if(date)date.required=action.value==='reschedule'}
 action?.addEventListener('change',dates);if(action)dates();
});
