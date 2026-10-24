document.addEventListener('DOMContentLoaded',()=>{
 const button=document.querySelector('#sidebar-toggle');if(!button)return;
 const key='crm.sidebar.collapsed.'+document.body.dataset.user;
 function apply(collapsed){document.body.classList.toggle('sidebar-collapsed',collapsed);button.setAttribute('aria-expanded',String(!collapsed));button.setAttribute('aria-label',collapsed?'Развернуть меню':'Свернуть меню');button.textContent=collapsed?'☰':'‹ Свернуть меню';try{localStorage.setItem(key,collapsed?'1':'0')}catch(e){}}
 let collapsed=false;try{collapsed=localStorage.getItem(key)==='1'}catch(e){}apply(collapsed);
 button.onclick=()=>apply(!document.body.classList.contains('sidebar-collapsed'));
 document.querySelectorAll('.app-nav a').forEach(a=>{a.title=a.textContent.trim();a.setAttribute('aria-label',a.textContent.trim())});
});
