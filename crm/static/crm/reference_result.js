const result=document.querySelector('#reference-result');if(result)window.parent.postMessage(JSON.parse(result.textContent),location.origin);

document.querySelector('form[data-unsaved]')?.addEventListener('input',event=>event.currentTarget.dataset.dirty='1');
