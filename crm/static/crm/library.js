document.addEventListener('DOMContentLoaded',()=>{
 const button=document.querySelector('#copy-library-text'),body=document.querySelector('#library-text'),status=document.querySelector('#library-copy-status');
 button?.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(body.innerText);status.textContent='Текст скопирован.'}catch(e){status.textContent='Не удалось скопировать автоматически. Выделите нужный текст и скопируйте его.'}});
 document.querySelector('.library-tree [aria-current=page]')?.scrollIntoView({block:'nearest'});
});
