document.addEventListener('DOMContentLoaded',()=>{
 const clamp=value=>Math.max(48,Math.min(1200,Math.round(value)));
 const defaults={number:100,date:95,customer:220,name:220,operator:160,country:110,hotel:210,start:95,end:95,source_currency:75,amount:120,paid:120,debt:120,cost:120,profit:120,operator_due:115,payment_method:160,notes:230,departure:140,operator_paid_in_full:125,adults:65,children:65,phone:170,email:190,inn:130,contracts:85,incoming:120,outgoing:120,currency:75,rate:90,kind:170,title:260,due:115,contacts:210,employee:160,status:150,select:48};
 document.querySelectorAll('table[data-layout-key]').forEach(table=>{
  if(!table.tHead?.rows.length)return;
  const key=table.dataset.layoutKey,headers=[...table.tHead.rows[0].cells];
  let saved={...(window.crmInterface?.preferences.column_widths?.[key]||{})},widths={...saved};
  headers.forEach(header=>{const id=header.dataset.col;if(!id)return;if(!widths[id])widths[id]=defaults[id]||140});
  const group=document.createElement('colgroup');table.prepend(group);table.classList.add('column-resizable');
  let frozenCells=[];
  function frozen(){
   let offset=0;
   [...table.tHead.rows[0].cells].filter(h=>!h.hidden&&h.classList.contains('frozen-column')).forEach(h=>{table.style.setProperty('--freeze-'+h.dataset.col,offset+'px');offset+=h.getBoundingClientRect().width});
  }
  function layout(){
   const scroll=table.closest('.journal-scroll');if(scroll)scroll.style.maxHeight=Math.max(160,innerHeight-Math.max(0,scroll.getBoundingClientRect().top)-12)+'px';
   const ordered=[...table.tHead.rows[0].cells];group.replaceChildren();let total=0;
   ordered.forEach(header=>{const id=header.dataset.col,col=document.createElement('col');col.dataset.col=id;col.style.width=(header.hidden?0:widths[id]||140)+'px';col.hidden=header.hidden;group.append(col);if(!header.hidden)total+=widths[id]||140});
   table.style.setProperty('--table-width',total+'px');
   let top=0;[...table.tHead.rows].forEach(row=>{[...row.cells].forEach(cell=>cell.style.setProperty('--header-row-top',top+'px'));top+=row.getBoundingClientRect().height});
   frozenCells=[...table.querySelectorAll('.frozen-column')];frozenCells.forEach(cell=>cell.style.setProperty('--frozen-left','var(--freeze-'+cell.dataset.col+',0px)'));frozen();
  }
  function change(id,width){widths[id]=clamp(width);const col=[...group.children].find(c=>c.dataset.col===id);if(col)col.style.width=widths[id]+'px';let total=0;[...table.tHead.rows[0].cells].forEach(h=>{if(!h.hidden)total+=widths[h.dataset.col]||140});table.style.setProperty('--table-width',total+'px');frozen();}
  async function persist(id){
   const value=widths[id];
   try{await window.crmInterface.save({table:key,widths:{[id]:value}});saved[id]=value}
   catch(e){if(widths[id]===value){widths[id]=saved[id]||defaults[id]||140;layout()}}
  }
  headers.forEach(header=>{
   const id=header.dataset.col;if(!id)return;
   const handle=document.createElement('span');handle.className='column-resize-handle';handle.tabIndex=0;handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');handle.setAttribute('aria-label','Ширина колонки: '+(header.dataset.label||header.textContent.trim()));handle.title='Перетащите для изменения ширины. Двойной щелчок — по содержимому. Стрелки ← → — изменить ширину.';
   handle.addEventListener('click',event=>{event.preventDefault();event.stopPropagation()});handle.addEventListener('dragstart',event=>event.preventDefault());
   handle.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;event.preventDefault();event.stopPropagation();const start=event.clientX,original=header.getBoundingClientRect().width,draggable=header.draggable;header.draggable=false;document.body.classList.add('resizing-columns');
    function move(e){change(id,original+e.clientX-start);handle.setAttribute('aria-valuenow',String(widths[id]))}
    function finish(e){document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',finish);document.removeEventListener('pointercancel',cancel);document.body.classList.remove('resizing-columns');header.draggable=draggable;if(e.clientX!==start)persist(id)}
    function cancel(){change(id,original);document.removeEventListener('pointermove',move);document.removeEventListener('pointerup',finish);document.removeEventListener('pointercancel',cancel);document.body.classList.remove('resizing-columns');header.draggable=draggable}
    document.addEventListener('pointermove',move);document.addEventListener('pointerup',finish);document.addEventListener('pointercancel',cancel);
   });
   handle.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();event.stopPropagation();change(id,widths[id]+(event.key==='ArrowRight'?1:-1)*(event.shiftKey?32:8));persist(id)});
   handle.addEventListener('dblclick',event=>{
    event.preventDefault();event.stopPropagation();const canvas=document.createElement('canvas'),context=canvas.getContext('2d');let width=80;
    if(context){context.font=getComputedStyle(header).font;table.querySelectorAll('th[data-col="'+id+'"],td[data-col="'+id+'"]').forEach(cell=>{if(cell.closest('.column-search-row'))return;for(const line of cell.innerText.split('\n'))width=Math.max(width,context.measureText(line.trim()).width+28)})}
    change(id,width);persist(id);
   });header.append(handle);
  });
  const reset=document.createElement('button');reset.type='button';reset.className='reset-column-widths';reset.textContent='Сбросить ширину колонок';reset.addEventListener('click',async()=>{try{await window.crmInterface.save({table:key,widths:null});saved={};widths={};headers.forEach(h=>widths[h.dataset.col]=defaults[h.dataset.col]||140);layout()}catch(e){}});const actions=table.closest('.journal-scroll')?.previousElementSibling;if(actions?.classList.contains('column-search-actions'))actions.append(reset);else table.closest('.journal-scroll')?.before(reset);
  table.addEventListener('crm:columns',layout);document.addEventListener('crm:layout',layout);window.addEventListener('resize',layout);layout();
 });
});
