document.addEventListener('DOMContentLoaded',()=>{
 const button=document.getElementById('eta-add-answer'),total=document.getElementById('id_answers-TOTAL_FORMS');
 const rows=document.getElementById('eta-answer-rows'),template=document.getElementById('eta-empty-answer');
 if(!button||!total||!rows||!template)return;
 button.addEventListener('click',()=>{
  const index=Number(total.value);if(!Number.isInteger(index)||index<0||index>=50)return;
  const row=document.createElement('fieldset');row.innerHTML=template.innerHTML.replaceAll('__prefix__',String(index));rows.append(row);
  total.value=String(index+1);if(index+1>=50)button.disabled=true;total.dispatchEvent(new Event('change',{bubbles:true}));
 });
});
