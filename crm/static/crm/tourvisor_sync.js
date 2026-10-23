document.addEventListener('DOMContentLoaded',()=>{
 const form=document.querySelector('#sync-confirm');if(!form)return;
 const tour=form.querySelector('input[name=groups][value=tour]'),block=form.querySelector('.sync-task-moves');
 function toggleTasks(){if(!block)return;const enabled=!!tour?.checked;block.classList.toggle('disabled',!enabled);block.querySelectorAll('input').forEach(input=>input.disabled=!enabled);}
 tour?.addEventListener('change',toggleTasks);toggleTasks();
 const parse=v=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(v))return null;const [y,m,d]=v.split('-').map(Number);return Date.UTC(y,m-1,d)};
 const fields=[...form.querySelectorAll('[data-move-anchor]')];fields.forEach(f=>f.addEventListener('input',()=>f.dataset.manual='1'));
 const end=form.querySelector('#id_end');
 end?.addEventListener('change',()=>{if(tour)tour.checked=true;toggleTasks();const target=parse(end.value);if(target===null)return;fields.forEach(f=>{if(f.dataset.moveAnchor!=='end'||f.dataset.manual)return;const oldAnchor=parse(f.dataset.oldAnchor),oldDue=parse(f.dataset.oldDue);if(oldAnchor===null||oldDue===null)return;f.value=new Date(oldDue+target-oldAnchor).toISOString().slice(0,10);});});
 form.addEventListener('submit',()=>{form.querySelectorAll('button').forEach(b=>b.disabled=true)});
});
