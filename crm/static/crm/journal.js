document.addEventListener('DOMContentLoaded',()=>{
 const table=document.querySelector('#contracts'),form=document.querySelector('#journal-filters');if(!table)return;
 const key='crm.columns.v2.'+table.dataset.user,headers=[...table.tHead.rows[0].cells],ids=headers.map(h=>h.dataset.col);
 let state;try{state=JSON.parse(localStorage.getItem(key))}catch(e){}
 if(!state||!Array.isArray(state.order)||!Array.isArray(state.hidden))state={order:[],hidden:[]};
 state.order=[...new Set(state.order.filter(id=>ids.includes(id)).concat(ids))];state.hidden=state.hidden.filter(id=>ids.includes(id));
 function apply(){[...table.rows].forEach(r=>state.order.forEach(id=>{const c=[...r.cells].find(c=>c.dataset.col===id);if(c){r.append(c);c.hidden=state.hidden.includes(id)}}));if(table.hasAttribute('data-freeze-first')){const first=state.order.find(id=>!state.hidden.includes(id));[...table.rows].forEach(r=>[...r.cells].forEach(c=>c.classList.toggle('frozen-column',c.dataset.col===first)))}try{localStorage.setItem(key,JSON.stringify(state))}catch(e){}}
 headers.forEach(h=>{const id=h.dataset.col,label=document.createElement('label'),cb=document.createElement('input');cb.type='checkbox';cb.checked=!state.hidden.includes(id);cb.onchange=()=>{state.hidden=state.hidden.filter(v=>v!==id);if(!cb.checked)state.hidden.push(id);apply()};label.append(cb,document.createTextNode(h.dataset.label));document.querySelector('#columns').append(label);h.draggable=true;h.ondragstart=e=>{if(e.target.closest('details,button,input')){e.preventDefault();return}e.dataTransfer.setData('text/plain',id)};h.ondragover=e=>e.preventDefault();h.ondrop=e=>{e.preventDefault();const from=e.dataTransfer.getData('text/plain');if(!ids.includes(from)||from===id)return;state.order=state.order.filter(v=>v!==from);state.order.splice(state.order.indexOf(id),0,from);apply()}});apply();
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
  window.addEventListener('scroll',e=>{if(d.open&&!panel.contains(e.target)){const box=summary.getBoundingClientRect();if(box.bottom<0||box.top>innerHeight||box.right<0||box.left>innerWidth)d.open=false;else position()}},true);
 });
});
