document.addEventListener('DOMContentLoaded',()=>{
 const tabs=[...document.querySelectorAll('[data-tab]')],panels=[...document.querySelectorAll('[data-panel]')];
 function activate(name){if(!panels.some(p=>p.dataset.panel===name))name='overview';tabs.forEach(t=>{const current=t.dataset.tab===name;t.classList.toggle('active',current);t.setAttribute('aria-current',current?'page':'false')});panels.forEach(p=>p.hidden=p.dataset.panel!==name);const current=tabs.find(t=>t.dataset.tab===name);if(current&&current.parentElement.scrollWidth>current.parentElement.clientWidth)current.scrollIntoView({block:'nearest',inline:'center'});}
 activate(document.querySelector('[data-active-tab]')?.dataset.activeTab||new URL(location.href).searchParams.get('tab')||'overview');
 tabs.forEach(tab=>tab.addEventListener('click',e=>{e.preventDefault();activate(tab.dataset.tab);const url=new URL(location.href);url.searchParams.set('tab',tab.dataset.tab);history.replaceState(null,'',url);}));
 const forms=[...document.querySelectorAll('form[data-unsaved]')];let leaving=false;
 forms.forEach(form=>{form.addEventListener('input',()=>form.dataset.dirty='1');form.addEventListener('change',()=>form.dataset.dirty='1');form.addEventListener('submit',e=>{
  if(e.submitter?.dataset.confirm&&!confirm(e.submitter.dataset.confirm)){e.preventDefault();return;}
  if(form.hasAttribute('data-async'))return;
  if(forms.some(f=>f!==form&&f.dataset.dirty==='1')&&!confirm('В других разделах есть несохранённые правки. Сохранить только этот раздел?')){e.preventDefault();return;}leaving=true;
 });});
 document.querySelectorAll('.cancel-changes').forEach(a=>a.addEventListener('click',e=>{if(forms.some(f=>f.dataset.dirty==='1')&&!confirm('Выйти без сохранения изменений?'))e.preventDefault();else leaving=true;}));
 window.addEventListener('beforeunload',e=>{if(!leaving&&forms.some(f=>f.dataset.dirty==='1')){e.preventDefault();e.returnValue='';}});
 document.querySelectorAll('.errorlist').forEach(error=>{for(let parent=error.parentElement;parent;parent=parent.parentElement){if(parent.tagName==='DETAILS')parent.open=true;}});
});
