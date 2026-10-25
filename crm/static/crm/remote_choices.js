document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('select[data-remote-choices]').forEach(select=>{
  const search=document.createElement('input');search.type='search';search.placeholder=select.dataset.searchLabel||'Найти туриста по ФИО';search.setAttribute('aria-label',search.placeholder);search.autocomplete='off';select.before(search);
  let timer,controller;
  search.addEventListener('input',()=>{clearTimeout(timer);controller?.abort();if(search.value.trim().length<2)return;timer=setTimeout(async()=>{
   controller=new AbortController();try{const response=await fetch(select.dataset.remoteChoices+'?q='+encodeURIComponent(search.value),{signal:controller.signal,cache:'no-store'});if(!response.ok)return;const data=await response.json(),current=select.selectedOptions[0];const value=select.value;select.replaceChildren(new Option('---------',''));if(value&&current)select.add(new Option(current.text,value,true,true));for(const item of data.choices){if(String(item.id)!==value)select.add(new Option(item.label,item.id));}select.value=value;search.title=data.choices.length?'Выберите найденное значение в списке ниже.':'Совпадений нет.';}catch(error){if(error.name!=='AbortError')search.title='Не удалось получить варианты. Повторите поиск.';}
  },250);});
 });
});
