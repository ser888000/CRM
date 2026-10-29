document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-task-done]').forEach(button=>{
  const input=document.getElementById(button.dataset.taskDone);
  if(!input)return;
  let done=['1','true','on'].includes(input.value.toLowerCase());
  function render(){
   input.value=done?'1':'0';button.classList.toggle('is-paid',done);
   button.setAttribute('aria-pressed',String(done));button.textContent=done?'✓ Выполнено':'○ Запланировано';
  }
  render();button.addEventListener('click',()=>{done=!done;render();input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));});
 });
});
