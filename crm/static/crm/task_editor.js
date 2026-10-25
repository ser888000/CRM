document.addEventListener('DOMContentLoaded',()=>{
 const customer=document.querySelector('#id_customer'),link=document.querySelector('#task-customer-link');let controller;
 customer?.addEventListener('change',async()=>{
  controller?.abort();for(const name of ['email','phone'])document.querySelector('#id_customer_'+name).value='';link.hidden=true;if(!customer.value)return;
  controller=new AbortController();try{const response=await fetch('/tasks/customer/'+encodeURIComponent(customer.value)+'/',{signal:controller.signal});if(!response.ok)return;const data=await response.json();for(const name of ['email','phone'])document.querySelector('#id_customer_'+name).value=data[name];link.href=data.url;link.hidden=false;}catch(error){}
 });
 const booking=document.querySelector('#task-booking-links');let timer,bookingController;
 async function refreshBooking(){
  bookingController?.abort();bookingController=new AbortController();const params=new URLSearchParams();for(const key of ['contract','operator'])params.set(key,document.querySelector('#id_'+key).value);params.set('number',document.querySelector('#id_booking_number').value);
  try{const response=await fetch('/tasks/booking/?'+params,{signal:bookingController.signal});if(!response.ok)return;const data=await response.json();booking.replaceChildren();for(const item of data.bookings){const a=document.createElement('a');a.href=item.url;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Бронь '+item.number+' ↗';booking.append(a);}}catch(error){}
 }
 for(const name of ['contract','operator','booking_number'])document.querySelector('#id_'+name)?.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(refreshBooking,200)});
});
