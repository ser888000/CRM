document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('table').forEach(table=>table.addEventListener('dblclick',event=>{
  if(event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
  if(event.target.closest('a,button,input,select,textarea,summary,details,[contenteditable]'))return;
  const row=event.target.closest('tr[data-open-row]');
  if(row&&row.closest('table')===table){const link=row.querySelector('a[data-row-link]');if(link){event.preventDefault();link.click()}}
 }));
});
