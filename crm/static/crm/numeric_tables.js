document.addEventListener('DOMContentLoaded',()=>{
 const numeric=/^[+−-]?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d{1,2})?\s*(?:₽|%)?$/;
 document.querySelectorAll('table tbody td,table tbody th,table tfoot td').forEach(cell=>{
  if(!cell.querySelector('input,select,textarea,button')&&numeric.test(cell.textContent.trim()))cell.classList.add('numeric');
 });
});
