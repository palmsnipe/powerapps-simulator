'use strict';
// Clock pulses carry no formula values or elapsed time. Python owns scheduling.
let timerPolling=false;
function renderTimer(node,wrapper,mode){
  let button=wrapper.querySelector(':scope > .fx-timer');
  if(!button)button=element('button',{type:'button',class:'fx-button fx-timer'});
  button.textContent=node.props.Text??'Start / pause';button.disabled=mode!=='Edit';
  button.setAttribute('aria-label',node.props.AccessibleLabel||node.props.Text||node.name);
  button.setAttribute('aria-pressed',String(!!node.timer?.running));
  button.style.background=node.props.Fill==='transparent'?'#0f6cbd':node.props.Fill||'#0f6cbd';
  button.style.color=node.props.Color||'#fff';
  button.onclick=event=>{event.stopPropagation();if(mode==='Edit'&&!$('inspect-toggle').checked)emit(node,'OnSelect');};
  return button;
}
function showTimerClock(){
  const info=state?.timers;$('timer-controls').hidden=!info;
  if(!info)return;
  $('timer-clock').textContent=(info.elapsed_ms/1000).toFixed(1)+' s';
  $('timer-pause').textContent=info.playing?'Pause time':'Play time';
  $('timer-pause').setAttribute('aria-pressed',String(!info.playing));
}
setInterval(()=>{
  if(!state?.timers||timerPolling||pressedButton)return;
  const token=state.timers.token,playing=!state.inspection&&!$('inspect-toggle').checked;
  timerPolling=true;
  enqueue(async()=>{
    try{
      if(state?.timers?.token!==token)return;
      const reply=await api('/api/time/pulse',{token,playing});
      if(reply.stale)return;state=reply;renderState();
    }finally{timerPolling=false;}
  });
},250);

document.addEventListener('DOMContentLoaded',()=>{
  $('timer-pause').onclick=()=>enqueue(async()=>{state=await api('/api/time/control',{token:state.timers.token,playing:!state.timers.playing});renderState();});
  $('timer-step').onclick=()=>enqueue(async()=>{state=await api('/api/time/advance',{token:state.timers.token,milliseconds:1000});renderState();});
});
