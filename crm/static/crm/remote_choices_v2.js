document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('select[data-remote-choices]').forEach(select=>{
  const box=document.createElement('span');box.className='remote-choice';select.before(box);box.append(select);
  const search=document.createElement('input');search.type='search';search.id=select.id+'_search';search.placeholder=select.dataset.searchLabel||'Найти туриста по ФИО';search.setAttribute('aria-label',search.placeholder);search.autocomplete='off';search.disabled=select.disabled;search.setAttribute('role','combobox');search.setAttribute('aria-autocomplete','list');search.setAttribute('aria-expanded','false');
  const list=document.createElement('span');list.className='remote-results';list.id=search.id+'_results';list.role='listbox';list.hidden=true;search.setAttribute('aria-controls',list.id);
  const status=document.createElement('small');status.role='status';box.prepend(search,list,status);select.hidden=true;const required=select.required;select.required=false;search.required=required;
  document.querySelectorAll('label').forEach(label=>{if(label.htmlFor===select.id)label.htmlFor=search.id});
  let timer,controller,sequence=0,items=[],index=-1;
  function close(){list.hidden=true;search.setAttribute('aria-expanded','false');search.removeAttribute('aria-activedescendant');index=-1}
  function sync(){search.value=select.value?(select.selectedOptions[0]?.textContent||''):'';search.setCustomValidity('');status.textContent='';close()}
  function choose(item){let option=[...select.options].find(o=>o.value===String(item.id));if(!option){option=new Option(item.label,item.id);select.add(option)}select.value=String(item.id);select.dispatchEvent(new Event('change',{bubbles:true}));status.textContent='Выбрано';search.focus()}
  select.addEventListener('change',sync);sync();
  search.addEventListener('input',()=>{
   clearTimeout(timer);controller?.abort();const current=++sequence;const query=search.value.trim();if(select.value){select.value='';select.dispatchEvent(new Event('change',{bubbles:true}));search.value=query}close();items=[];
   search.setCustomValidity(query?'Выберите значение из подсказок.':'');if(query.length<2){status.textContent=query?'Введите минимум две буквы.':'';return}status.textContent='Ищем…';
   timer=setTimeout(async()=>{controller=new AbortController();try{const response=await fetch(select.dataset.remoteChoices+'?q='+encodeURIComponent(query),{signal:controller.signal,cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();if(current!==sequence)return;items=data.choices;list.replaceChildren();items.forEach((item,i)=>{const option=document.createElement('span');option.role='option';option.id=list.id+'_'+i;option.textContent=item.label;option.addEventListener('mousedown',e=>e.preventDefault());option.onclick=()=>choose(item);list.append(option)});list.hidden=!items.length||document.activeElement!==search;search.setAttribute('aria-expanded',String(!list.hidden));status.textContent=items.length?'Выберите подходящую запись.':'Совпадений нет.';}catch(error){if(error.name!=='AbortError'&&current===sequence)status.textContent='Не удалось выполнить поиск. Попробуйте ещё раз.'}},250);
  });
  search.addEventListener('keydown',event=>{if(event.key==='Escape'){close();return}if(['ArrowDown','ArrowUp'].includes(event.key)&&items.length){event.preventDefault();list.hidden=false;index=index<0?(event.key==='ArrowDown'?0:items.length-1):(index+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;[...list.children].forEach((item,i)=>item.setAttribute('aria-selected',String(i===index)));search.setAttribute('aria-activedescendant',list.children[index].id);list.children[index].scrollIntoView({block:'nearest'})}if(event.key==='Enter'){event.preventDefault();event.stopPropagation();if(items.length&&!list.hidden)choose(items[index<0?0:index])}});
  search.addEventListener('focus',()=>{if(items.length&&!select.value){list.hidden=false;search.setAttribute('aria-expanded','true')}});
  search.addEventListener('blur',close);
 });
});
