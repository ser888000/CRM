document.addEventListener('DOMContentLoaded',()=>{
 const parse=v=>{if(!v)return null;let m=v.match(/^(\d{4})-(\d{2})-(\d{2})$/);if(m)return new Date(+m[1],+m[2]-1,+m[3]);m=v.match(/^(\d{2})\.(\d{2})\.(\d{4})$/);return m?new Date(+m[3],+m[2]-1,+m[1]):null};
 const fields=[...document.querySelectorAll('[data-task-anchor]')];
 fields.forEach(f=>f.addEventListener('input',()=>f.dataset.manual='1'));
 function update(){const created=parse(document.querySelector('#id_date')?.value);fields.forEach(f=>{
  const checkbox=document.querySelector(`input[name="task_templates"][value="${f.dataset.taskId}"]`);
  f.required=!!checkbox?.checked;
  if(f.dataset.manual)return;
  const id={created:'date',start:'start',end:'end'}[f.dataset.taskAnchor];
  let d=parse(document.querySelector('#id_'+id)?.value);if(!d)return;
  d.setDate(d.getDate()+Number(f.dataset.taskOffset));if(created&&d<created)d=created;
  f.value=[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');
 });}
 ['date','start','end'].forEach(id=>document.querySelector('#id_'+id)?.addEventListener('change',update));
 document.querySelectorAll('input[name="task_templates"]').forEach(c=>c.addEventListener('change',update));
 // Preserve submitted dates on validation errors.
 if(!document.querySelector('.errornote'))update();
});
