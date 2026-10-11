'use strict';
function renderClassicButton(node,wrapper){
  const p=node.props||{},mode=node._effectiveMode;
  let button=wrapper.querySelector(':scope > .fx-button');
  if(!button)button=element('button',{class:'fx-button fx-classic-button'});
  button.type='button';button._model=node;button.dataset.pressed=String(!!node.classic_button?.pressed);
  let caption=button.querySelector(':scope > span');
  if(!caption){caption=element('span');button.append(caption);}
  if(caption.textContent!==String(p.Text??''))caption.textContent=p.Text??'';
  button.disabled=mode!=='Edit'||!!button._pending||!!node.classic_button?.busy;
  button.setAttribute('aria-label',p.AccessibleLabel||p.Text||node.name);
  button.setAttribute('aria-busy',String(!!button._pending||!!node.classic_button?.busy));
  button.style.font='inherit';button.style.fontStyle=p.Italic?'italic':'normal';
  button.style.textDecoration=[p.Underline?'underline':'',p.Strikethrough?'line-through':''].filter(Boolean).join(' ');
  button.style.justifyContent={Left:'flex-start',Center:'center',Right:'flex-end',Justify:'space-between'}[p.Align]||'center';
  button.style.alignItems={Top:'flex-start',Middle:'center',Bottom:'flex-end'}[p.VerticalAlign]||'center';
  applyClassicPresentation(button,wrapper,node,button._pending?'Disabled':mode);
  button.onpointerdown=()=>beginPress(button._model,button.disabled);
  button.onkeydown=e=>{if(!e.repeat&&['Enter',' '].includes(e.key))beginPress(button._model,button.disabled);};
  button.onclick=event=>{
    if(button.disabled||$('inspect-toggle').checked)return;
    event.stopPropagation();
    const model=button._model,auto=model.classic_button?.auto_disable,hadFocus=document.activeElement===button;
    if(auto){button._pending=true;button.disabled=true;button.dataset.mode='Disabled';button.setAttribute('aria-busy','true');}
    enqueue(async()=>{
      try{state=await api('/api/event',{path:model.path,name:'OnSelect'});}
      finally{button._pending=false;button.removeAttribute('aria-busy');button.disabled=button._model._effectiveMode!=='Edit';button.dataset.mode=button._model._effectiveMode;}
      renderState();
      if(hadFocus&&document.activeElement===document.body&&button.isConnected&&!button.disabled)button.focus({preventScroll:true});
      if(selectedPath)await inspect(selectedPath);
    });
  };
  return button;
}
