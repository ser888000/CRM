document.addEventListener('DOMContentLoaded',()=>{
 const form=document.querySelector('#journal-filters');if(!form)return;
 form.querySelectorAll('[data-column-selected]').forEach(e=>e.remove());
 document.querySelectorAll('[data-sort]').forEach(b=>b.onclick=()=>{document.querySelector('#journal-sort').value=b.dataset.sort;form.requestSubmit()});
 const filters=[...document.querySelectorAll('.column-filter')];
 filters.forEach(d=>{
  const panel=d.querySelector('.column-options'),summary=d.querySelector('summary');
  panel.querySelectorAll('input,button,select').forEach(input=>input.setAttribute('form',form.id));
  panel.querySelector('[type=search]').oninput=e=>panel.querySelectorAll('label').forEach(l=>l.hidden=!l.textContent.toLocaleLowerCase('ru').includes(e.target.value.toLocaleLowerCase('ru')));
  if(panel.dataset.choicesUrl){
   const selected=new Set([...panel.querySelectorAll('input[type=checkbox]:checked')].map(c=>c.value));
   const name='f_'+panel.dataset.column;
   function sync(){form.querySelectorAll('input[data-remote-column="'+panel.dataset.column+'"]').forEach(c=>c.remove());for(const value of selected){const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;input.dataset.remoteColumn=panel.dataset.column;form.append(input);}}
   function bind(){panel.querySelectorAll('input[type=checkbox]').forEach(c=>{c.removeAttribute('name');c.onchange=()=>{if(c.checked)selected.add(c.value);else selected.delete(c.value);sync();};});}
   bind();sync();let timer,controller;
   panel.querySelector('[type=search]').oninput=e=>{clearTimeout(timer);controller?.abort();timer=setTimeout(async()=>{
    controller=new AbortController();const params=new URLSearchParams(new FormData(form));params.set('choice_column',panel.dataset.column);params.set('choice_search',e.target.value);
    try{const response=await fetch(panel.dataset.choicesUrl+'?'+params,{signal:controller.signal,cache:'no-store'});if(!response.ok)return;const data=await response.json();panel.querySelectorAll('label').forEach(l=>l.remove());const apply=panel.querySelector('button:last-child');
     for(const value of [...new Set([...selected,...data.values])]){const label=document.createElement('label'),c=document.createElement('input');c.type='checkbox';c.value=value;c.checked=selected.has(value);label.append(c,document.createTextNode(value));panel.insertBefore(label,apply);}bind();
    }catch(error){if(error.name!=='AbortError')panel.querySelector('[type=search]').title='Не удалось загрузить варианты. Повторите поиск.';}
   },250);};
   panel.querySelector('.clear-column').onclick=()=>{selected.clear();panel.querySelectorAll('input[type=checkbox]').forEach(c=>c.checked=false);sync();};
  }

  if(!panel.dataset.choicesUrl)panel.querySelector('.clear-column').onclick=()=>panel.querySelectorAll('[type=checkbox]').forEach(c=>c.checked=false);

  function position(){const box=summary.getBoundingClientRect(),width=Math.min(320,innerWidth-20);panel.style.width=width+'px';panel.style.minWidth='0';panel.style.left=Math.max(10,Math.min(box.left,innerWidth-width-10))+'px';const below=innerHeight-box.bottom-16,above=box.top-16;const height=Math.max(80,Math.min(350,Math.max(below,above),panel.scrollHeight||350));panel.style.maxHeight=height+'px';panel.style.top=(below>=Math.min(220,height)?box.bottom+6:Math.max(10,box.top-height-6))+'px'}
  d.addEventListener('toggle',()=>{if(d.open){filters.forEach(other=>{if(other!==d)other.open=false});document.body.append(panel);panel.classList.add('floating-filter');position()}else{panel.classList.remove('floating-filter');d.append(panel)}});
  document.addEventListener('click',e=>{if(d.open&&!d.contains(e.target)&&!panel.contains(e.target))d.open=false});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&d.open){d.open=false;summary.focus()}});
  window.addEventListener('resize',()=>{if(d.open)position()});
  window.addEventListener('scroll',e=>{if(d.open&&!panel.contains(e.target))d.open=false},true);
 });
});
