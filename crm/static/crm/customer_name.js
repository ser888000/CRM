document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('input[name="name"],input[name$="-name"]').forEach(output=>{
  const form=output.form;if(!form)return;const prefix=output.name.slice(0,-4);
  const parts=['surname','given_name','patronymic'].map(n=>form.elements.namedItem(prefix+n));
  if(!parts.every(Boolean))return;
  function update(){output.value=parts.map(i=>i.value.trim()).filter(Boolean).join(' ');output.dispatchEvent(new Event('change',{bubbles:true}));}
  parts.forEach(input=>input.addEventListener('input',update));
 });
});
