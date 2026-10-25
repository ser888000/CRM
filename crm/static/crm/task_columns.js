document.addEventListener('DOMContentLoaded',()=>{
 const form=document.querySelector('#journal-filters');if(!form)return;
 form.querySelectorAll('[data-column-selected]').forEach(e=>e.remove());
 document.querySelectorAll('[data-sort]').forEach(b=>b.onclick=()=>{document.querySelector('#journal-sort').value=b.dataset.sort;form.requestSubmit()});
 const filters=[...document.querySelectorAll('.column-filter')];
 filters.forEach(d=>{
  const panel=d.querySelector('.column-options'),summary=d.querySelector('summary');
  panel.querySelectorAll('input,button,select').forEach(input=>input.setAttribute('form',form.id));
  panel.querySelector('[type=search]').oninput=e=>panel.querySelectorAll('label').forEach(l=>l.hidden=!l.textContent.toLocaleLowerCase('ru').includes(e.target.value.toLocaleLowerCase('ru')));
  panel.querySelector('.clear-column').onclick=()=>panel.querySelectorAll('[type=checkbox]').forEach(c=>c.checked=false);
  function position(){const box=summary.getBoundingClientRect(),width=Math.min(320,innerWidth-20);panel.style.width=width+'px';panel.style.minWidth='0';panel.style.left=Math.max(10,Math.min(box.left,innerWidth-width-10))+'px';const below=innerHeight-box.bottom-16,above=box.top-16;const height=Math.max(80,Math.min(350,Math.max(below,above),panel.scrollHeight||350));panel.style.maxHeight=height+'px';panel.style.top=(below>=Math.min(220,height)?box.bottom+6:Math.max(10,box.top-height-6))+'px'}
  d.addEventListener('toggle',()=>{if(d.open){filters.forEach(other=>{if(other!==d)other.open=false});document.body.append(panel);panel.classList.add('floating-filter');position()}else{panel.classList.remove('floating-filter');d.append(panel)}});
  document.addEventListener('click',e=>{if(d.open&&!d.contains(e.target)&&!panel.contains(e.target))d.open=false});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&d.open){d.open=false;summary.focus()}});
  window.addEventListener('resize',()=>{if(d.open)position()});
  window.addEventListener('scroll',e=>{if(d.open&&!panel.contains(e.target))d.open=false},true);
 });
});
