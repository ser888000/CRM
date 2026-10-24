document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('input[name="name"],input[name$="-name"]').forEach(output=>{
  const form=output.form;if(!form)return;const prefix=output.name.slice(0,-4);
  const get=name=>form.elements.namedItem(prefix+name),parts=['surname','given_name','patronymic'].map(get),kind=get('kind'),company=get('company_name');
  if(!parts.every(Boolean))return;
  function update(){output.value=kind?.value==='company'?(company?.value.trim()||''):parts.map(i=>i.value.trim()).filter(Boolean).join(' ');output.dispatchEvent(new Event('change',{bubbles:true}));}
  parts.forEach(input=>input.addEventListener('input',update));company?.addEventListener('input',update);
  function visibility(){
   const legal=kind?.value==='company';
   const legalNames=['company_name','inn','kpp','ogrn','legal_address','bank_name','bik','account','correspondent_account','representative','representative_basis'];
   const personNames=['surname','given_name','patronymic','birthday','passport_type','passport_number','passport_issued','passport_issued_by','passport_code','passport','address'];
   legalNames.forEach(n=>{const node=get(n)?.closest('.field,.form-row');if(node)node.hidden=!legal});
   personNames.forEach(n=>{const node=get(n)?.closest('.field,.form-row');if(node)node.hidden=legal});
   const label=form.querySelector(`[for="${output.id}"]`);if(label)label.textContent=legal?'Наименование заказчика':'ФИО заказчика';
   form.querySelectorAll('.passport-import').forEach(node=>node.hidden=legal);
  }
  kind?.addEventListener('change',()=>{update();visibility()});visibility();
 });
});
