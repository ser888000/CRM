document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('form[data-unsaved]').forEach(form=>{
  const action=form.querySelector('[name=action]')?.value;if(!['customer','tourist'].includes(action)||!form.querySelector('button:not([type]),button[type=submit]'))return;
  const file=document.createElement('input');file.type='file';file.accept='image/jpeg,image/png';file.hidden=true;
  const button=document.createElement('button');button.type='button';button.textContent='Загрузить паспорт';
  const status=document.createElement('p');status.className='passport-status';status.role='status';
  const wrapper=document.createElement('div');wrapper.className='passport-import';const details=document.createElement('details'),summary=document.createElement('summary'),recognized=document.createElement('pre');summary.textContent='Распознанный текст';recognized.style.whiteSpace='pre-wrap';details.append(summary,recognized);details.hidden=true;wrapper.append(button,file,status,details);form.prepend(wrapper);
  button.onclick=()=>file.click();file.onchange=async()=>{
   if(!file.files.length)return;if(file.files[0].size>6*1024*1024){status.textContent='Размер файла больше 6 МБ. Уменьшите изображение и повторите загрузку.';file.value='';return}const data=new FormData();data.set('kind',action);data.set('passport',file.files[0]);
   details.hidden=true;recognized.textContent='';button.disabled=true;status.textContent='Распознаём на сервере…';
   try{
    const response=await fetch('/passport/recognize/',{method:'POST',headers:{'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},body:data});
    if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('Сервер не завершил распознавание. Повторите попытку или загрузите отдельно страницу с данными.');
    const result=await response.json();if(!response.ok)throw new Error(result.error||'Ошибка распознавания');
    const fields=Object.entries(result.fields).map(([key,value])=>({input:[...form.elements].find(e=>e.name.endsWith('-'+key)),value})).filter(p=>p.input);
    if(fields.length&&confirm('Заполнить распознанные поля в этой форме? Уже введённые значения этих полей будут заменены. Перед сохранением проверьте результат.')){
     fields.forEach(({input,value})=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}))});
    }
    status.textContent=result.message;recognized.textContent=result.recognized_text||'';details.hidden=!recognized.textContent;
   }catch(error){status.textContent=error.message||'Связь с сервером прервалась. Повторите попытку.'}
   finally{button.disabled=false;file.value=''}
  };
  if(form.querySelector('[name$="-kind"]')?.value==='company')wrapper.hidden=true;
 });
});
