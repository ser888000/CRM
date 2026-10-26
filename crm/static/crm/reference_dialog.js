document.addEventListener('DOMContentLoaded',()=>{
 const dialog=document.createElement('dialog');dialog.className='reference-dialog';const header=document.createElement('div');header.className='dialog-header';const title=document.createElement('strong');title.textContent='Справочник';const close=document.createElement('button');close.type='button';close.textContent='×';close.setAttribute('aria-label','Закрыть');const frame=document.createElement('iframe');frame.title='Добавление и редактирование справочника';header.append(title,close);dialog.append(header,frame);document.body.append(dialog);let active;
 close.onclick=()=>{if(frame.contentDocument?.querySelector('form[data-dirty="1"]')&&!confirm('Закрыть окно? Несохранённые изменения в нём будут потеряны.'))return;dialog.close();frame.src='about:blank';active=null};dialog.addEventListener('cancel',event=>{event.preventDefault();close.click()});
 document.querySelectorAll('[data-reference-target]').forEach(button=>{
  const field=document.getElementById(button.dataset.referenceTarget);if(!field)return;
  const edit=!!button.dataset.referenceEdit,base=button.dataset.referenceEdit||button.dataset.referenceAdd,mode=button.dataset.referenceMode;
  function state(){if(edit)button.disabled=!field.value}field.addEventListener('change',state);field.addEventListener('input',state);state();
  button.onclick=async()=>{
   let pk=field.value;if(edit&&mode!=='id'){const response=await fetch(base+'resolve/?'+new URLSearchParams({value:pk,mode}));if(!response.ok){alert('Не удалось открыть справочник.');return}pk=(await response.json()).id;if(!pk){alert('Значение не найдено в справочнике однозначно. Выберите вариант из подсказок или добавьте запись.');return}}
   active={field,mode,base,old:field.value};title.textContent=edit?'Редактирование справочника':'Добавление в справочник';frame.src=base+(edit?encodeURIComponent(pk)+'/':'new/');dialog.showModal();
  };
 });
 document.querySelectorAll('[data-reference-open]').forEach(link=>link.addEventListener('click',event=>{if(event.ctrlKey||event.metaKey||event.shiftKey)return;event.preventDefault();active={reload:true};title.textContent='Редактирование заказчика';frame.src=link.dataset.referenceOpen;dialog.showModal()}));
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==frame.contentWindow||event.data?.type!=='crm-reference-saved'||!active)return;
  if(active.reload){dialog.close();active=null;location.reload();return;}
  const data=event.data,{field,mode}=active,value=mode==='id'?data.id:mode==='code'?data.code:data.text;
  if(field.tagName==='SELECT'){let option=[...field.options].find(o=>o.value===String(value));if(!option){option=new Option((mode==='id'||mode==='code')?data.label:data.text,value);field.add(option)}else option.textContent=(mode==='id'||mode==='code')?data.label:data.text;field.value=value}else field.value=value;
  field.dispatchEvent(new CustomEvent('reference-saved',{detail:{old:active.old,name:data.text}}));field.dispatchEvent(new Event('change',{bubbles:true}));field.dispatchEvent(new Event('input',{bubbles:true}));dialog.close();frame.src='about:blank';active=null;
 });
});
