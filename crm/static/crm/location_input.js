document.addEventListener('DOMContentLoaded',()=>{
 const norm=s=>s.normalize('NFKC').toLocaleLowerCase('ru').replaceAll('ё','е').trim().replace(/\s+/g,' ');
 document.querySelectorAll('.crm-location-input').forEach((wrapper,index)=>{
  const input=wrapper.querySelector('input'),list=wrapper.querySelector('[role="listbox"]');
  const names=JSON.parse(wrapper.querySelector('script[type="application/json"]').textContent);
  list.id=input.id+'_choices';input.setAttribute('aria-controls',list.id);
  let selected=-1,items=[];
  function close(){list.hidden=true;selected=-1;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');}
  function choose(name){input.value=name;close();input.dispatchEvent(new Event('change',{bubbles:true}));}
  function render(){
   const query=norm(input.value);items=names.filter(n=>!query||norm(n).includes(query));selected=-1;list.replaceChildren();
   items.forEach((name,i)=>{
    const option=document.createElement('span');option.role='option';option.id=list.id+'_'+i;option.textContent=name;option.setAttribute('aria-selected','false');
    option.addEventListener('mousedown',e=>e.preventDefault());option.addEventListener('click',()=>choose(name));list.append(option);
   });
   list.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));input.removeAttribute('aria-activedescendant');
  }
  function highlight(){[...list.children].forEach((e,i)=>e.setAttribute('aria-selected',String(i===selected)));const e=list.children[selected];if(e){input.setAttribute('aria-activedescendant',e.id);e.scrollIntoView({block:'nearest'});}}
  input.addEventListener('input',render);input.addEventListener('focus',render);input.addEventListener('blur',close);
  input.addEventListener('keydown',e=>{
   if(e.key==='Escape'){close();return;}
   if(e.key==='ArrowDown'||e.key==='ArrowUp'){
    e.preventDefault();if(list.hidden)render();if(!items.length)return;
    selected=e.key==='ArrowDown'?(selected+1)%items.length:(selected-1+items.length)%items.length;highlight();
   }else if(e.key==='Enter'&&!list.hidden&&selected>=0){e.preventDefault();choose(items[selected]);}
  });
 });
});
