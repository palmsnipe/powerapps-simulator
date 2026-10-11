'use strict';
function renderModernButton(node,wrapper){
  const p=node.props||{},authored=new Set(node.button_authored||[]);
  const archived=!!node.canvas_button;
  let button=wrapper.querySelector(':scope > .fx-button');
  if(!button)button=element('button',{class:'fx-button'});
  button.classList.add('fx-modern-button');
  button.dataset.mode=node._effectiveMode;
  button.type='button';
  button._model=node;
  const layout=archived?({'Icon before':'IconBefore','Icon after':'IconAfter','Text only':'TextOnly','Icon only':'IconOnly'}[p.Layout]||'IconBefore'):p.Layout;
  const glyph=node.icon?iconGlyph(node.icon):null;
  if(glyph)glyph.style.transform=`rotate(${p.IconRotation??0}deg)`;
  const label=element('span',{},p.Text??'');
  const icon=layout!=='TextOnly'&&glyph?[glyph]:[],text=layout!=='IconOnly'?[label]:[];
  reconcile(button,layout==='IconAfter'?[...text,...icon]:[...icon,...text]);
  button.disabled=node._effectiveMode!=='Edit'||(archived&&(!!button._pending||node.canvas_button.busy));
  button.setAttribute('aria-label',p.AccessibleLabel||p.Text||node.name);
  const primary=(p.Appearance||'Primary')==='Primary',outlined=['Secondary','Outline'].includes(p.Appearance);
  button.style.background=primary?p.BasePaletteColor||'#0f6cbd':p.Appearance==='Secondary'?'#fff':'transparent';
  button.style.color=authored.has('Color')?p.Color||(primary?'white':'#242424'):p.FontColor||(primary?'white':p.Color||'#242424');
  button.style.font='inherit';
  if(archived){
    button.style.fontFamily=p.Font||'Segoe UI, sans-serif';button.style.fontSize=(p.FontSize||14)+'px';
    button.style.fontWeight=({Normal:'400',Semibold:'600',Bold:'700',Lighter:'300'}[p.FontWeight]||p.FontWeight||'normal');
  }
  button.style.fontStyle=(archived?p.FontItalic:p.Italic)?'italic':'normal';
  button.style.textDecoration=[(archived?p.FontUnderline:p.Underline)?'underline':'',(archived?p.FontStrikethrough:p.Strikethrough)?'line-through':''].filter(Boolean).join(' ');
  button.style.justifyContent={Left:'flex-start',Center:'center',Right:'flex-end',Justify:'space-between'}[p.Align]||'center';
  button.style.alignItems={Top:'flex-start',Middle:'center',Bottom:'flex-end'}[p.VerticalAlign]||'center';
  const border=authored.has('BorderThickness')?(p.BorderThickness??0):outlined?1:0;
  button.style.borderWidth=border+'px';button.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();
  button.style.borderColor=authored.has('BorderColor')?p.BorderColor||'transparent':outlined?'#cdd2da':'transparent';
  for(const corner of ['TopLeft','TopRight','BottomLeft','BottomRight']){
    const key=(archived?'BorderRadius':'Radius')+corner;
    button.style['border'+corner+'Radius']=authored.has(key)?(p[key]??0)+'px':archived&&authored.has('BorderRadius')?(p.BorderRadius??0)+'px':'4px';
  }
  for(const direction of ['Top','Bottom','Left','Right'])button.style['padding'+direction]=authored.has('Padding'+direction)?(p['Padding'+direction]??0)+'px':(['Left','Right'].includes(direction)?'8px':'2px');
  // The face owns its box decoration so padding/borders aren't applied twice.
  wrapper.style.padding='0px';wrapper.style.border='0px';wrapper.style.background='transparent';
  button.onpointerdown=archived?null:()=>beginPress(node,button.disabled);
  button.onkeydown=archived?null:event=>{if(!event.repeat&&['Enter',' '].includes(event.key))beginPress(node,button.disabled);};
  button.onclick=event=>{
    if($('inspect-toggle').checked||button.disabled)return;event.stopPropagation();
    if(!archived){emit(node,'OnSelect');return;}
    if(button._pending)return;
    const hadFocus=document.activeElement===button;
    button._pending=!!node.canvas_button.auto_disable;
    button.disabled=button._pending;
    button.setAttribute('aria-busy',String(button._pending));
    emit(node,'OnSelect').finally(()=>{
      button._pending=false;button.setAttribute('aria-busy','false');
      button.disabled=button._model._effectiveMode!=='Edit'||!!button._model.canvas_button?.busy;
      if(hadFocus&&button.isConnected&&!button.disabled&&button._model.tab_stop!==false&&document.activeElement===document.body)button.focus({preventScroll:true});
    });
  };
  return button;
}
