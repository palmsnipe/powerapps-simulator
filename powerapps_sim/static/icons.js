'use strict';
function iconGlyph(icon){
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('class','fx-fluent-glyph');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
  const use=document.createElementNS('http://www.w3.org/2000/svg','use');
  use.setAttribute('width','24');use.setAttribute('height','24');use.setAttribute('href','/static/fluent-icons.svg#'+icon.symbol);
  svg.append(use);return svg;
}
function renderModernIcon(node,wrapper){
  const p=node.props||{},interactive=!!node.selectable,tag=interactive?'button':'div';
  let face=wrapper.querySelector(':scope > .fx-icon-face');
  if(face?.tagName.toLowerCase()!==tag)face=null;
  if(!face)face=element(tag,{class:'fx-icon-face'});
  const label=p.AccessibleLabel||'';
  const mode=node._effectiveMode;
  if(interactive){
    face.type='button';face.disabled=mode!=='Edit';face.setAttribute('aria-label',label||p.Tooltip||node.name);
    face.removeAttribute('aria-hidden');face.removeAttribute('role');
    face.onclick=event=>{if(mode!=='Edit'||$('inspect-toggle').checked)return;event.stopPropagation();emit(node,'OnSelect');};
  }else{
    face.onclick=null;
    if(label){face.setAttribute('role','img');face.setAttribute('aria-label',label);face.removeAttribute('aria-hidden');}
    else{face.removeAttribute('role');face.removeAttribute('aria-label');face.setAttribute('aria-hidden','true');}
  }
  face.style.color=p.IconColor||'transparent';
  face.style.opacity=mode==='Disabled'?'.4':'1';
  const glyph=node.icon?iconGlyph(node.icon):null;
  if(glyph){glyph.style.width='100%';glyph.style.height='100%';glyph.style.transform=`rotate(${p.Rotation||0}deg)`;}
  reconcile(face,glyph?[glyph]:[]);
  for(const corner of ['TopLeft','TopRight','BottomLeft','BottomRight'])wrapper.style['border'+corner+'Radius']=(p['Radius'+corner]||0)+'px';
  if(p.BorderThickness)wrapper.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();
  return face;
}

function renderClassicIcon(node,wrapper){
  const p=node.props||{},mode=node._effectiveMode,button=Number(p.TabIndex)>=0,tag=button?'button':'div';
  let face=wrapper.querySelector(':scope > .fx-classic-icon');
  if(face?.tagName.toLowerCase()!==tag)face=null;
  if(!face)face=element(tag,{class:'fx-icon-face fx-classic-icon'});
  face.dataset.mode=mode;
  const label=p.AccessibleLabel||'';
  if(button){
    face.type='button';face.disabled=mode!=='Edit';face.setAttribute('aria-label',label||p.Tooltip||node.name);
    face.removeAttribute('aria-hidden');face.removeAttribute('role');
  }else{
    face.removeAttribute('aria-label');face.removeAttribute('role');
    if(label){face.setAttribute('role','img');face.setAttribute('aria-label',label);face.removeAttribute('aria-hidden');}
    else face.setAttribute('aria-hidden','true');
  }
  face.onclick=event=>{
    if(mode!=='Edit'||$('inspect-toggle').checked)return;
    // Even a blank button owns the click; it must not activate an ancestor.
    event.stopPropagation();if(node.selectable)emit(node,'OnSelect');
  };
  face.style.cursor=mode==='Edit'&&(button||node.selectable)?'pointer':'default';
  for(const [key,value] of Object.entries({color:p.Color,fill:p.Fill,border:p.BorderColor,'hover-color':p.HoverColor,'hover-fill':p.HoverFill,'hover-border':p.HoverBorderColor,'pressed-color':p.PressedColor,'pressed-fill':p.PressedFill,'pressed-border':p.PressedBorderColor,'disabled-color':p.DisabledColor,'disabled-fill':p.DisabledFill,'disabled-border':p.DisabledBorderColor,'focus-color':p.FocusedBorderColor}))face.style.setProperty('--classic-'+key,value||'transparent');
  face.style.setProperty('--classic-focus-width',(p.FocusedBorderThickness||0)+'px');
  face.style.borderWidth=(p.BorderThickness||0)+'px';face.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();
  for(const direction of ['Top','Bottom','Left','Right'])face.style['padding'+direction]=(p['Padding'+direction]||0)+'px';
  // The face owns colors/border/padding so all interaction states cover its box.
  wrapper.style.background='transparent';wrapper.style.border='0';wrapper.style.padding='0';
  const glyph=node.icon?iconGlyph(node.icon):null;
  if(glyph){glyph.style.width='100%';glyph.style.height='100%';glyph.style.transform=`rotate(${p.Rotation||0}deg)`;glyph.setAttribute('preserveAspectRatio',p.PreserveAspectRatio===false?'none':'xMidYMid meet');}
  reconcile(face,glyph?[glyph]:[]);return face;
}
