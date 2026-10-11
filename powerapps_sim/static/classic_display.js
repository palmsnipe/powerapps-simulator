'use strict';
// Stable DOM faces; Power Fx and shape geometry remain authoritative on Python.
function classicDisplayInteraction(face,node,label){
  const mode=node._effectiveMode,button=Number(node.props.TabIndex)>=0;
  face._model=node;face.tabIndex=button&&mode==='Edit'?0:-1;
  face.removeAttribute('aria-hidden');face.removeAttribute('aria-label');
  if(button){face.setAttribute('role','button');face.setAttribute('aria-disabled',String(mode!=='Edit'));if(label)face.setAttribute('aria-label',label);}
  else{face.removeAttribute('aria-disabled');face.removeAttribute('role');}
  face.style.cursor=mode==='Edit'&&(button||node.selectable)?'pointer':'default';
  face.onclick=event=>{
    const model=face._model;
    if(model._effectiveMode!=='Edit'||$('inspect-toggle').checked)return;
    event.stopPropagation();if(model.selectable)emit(model,'OnSelect');
  };
  face.onkeydown=event=>{
    if(face.tabIndex>=0&&face._model._effectiveMode==='Edit'&&!event.repeat&&['Enter',' '].includes(event.key)){
      event.preventDefault();face.click();
    }
  };
  return button;
}
function renderClassicLabel(node,wrapper){
  const p=node.props||{},metadata=node.classic_display||{};
  let face=wrapper.querySelector(':scope > .fx-classic-label');
  if(!face){face=element('div',{class:'fx-classic-label'});face.append(element('span',{class:'fx-label-content'}));}
  const caption=face.firstElementChild;
  const text=String(p.Text??'');if(caption.textContent!==text)caption.textContent=text;
  if(metadata.heading){caption.setAttribute('role','heading');caption.setAttribute('aria-level',String(metadata.heading));}
  else{caption.removeAttribute('role');caption.removeAttribute('aria-level');}
  caption.setAttribute('aria-live',metadata.live||'off');caption.setAttribute('aria-atomic',String((metadata.live||'off')!=='off'));
  face.style.textAlign=(p.Align||'Left').toLowerCase();
  face.style.lineHeight=String(p.LineHeight===undefined?1.2:p.LineHeight||0);face.style.fontSize=(p.Size===undefined?14:p.Size||0)+'px';face.style.whiteSpace=p.Wrap===false?'nowrap':'pre-wrap';
  face.style.overflowWrap=p.Wrap?'anywhere':'normal';
  face.style.display=metadata.scroll?'block':'flex';face.style.overflowY=metadata.scroll?'auto':'hidden';
  face.style.justifyContent=p.AutoHeight||p.VerticalAlign==='Top'?'flex-start':p.VerticalAlign==='Bottom'?'flex-end':'center';
  classicDisplayInteraction(face,node,'');
  applyClassicPresentation(face,wrapper,node,node._effectiveMode);
  return face;
}
function renderClassicShape(node,wrapper){
  const p=node.props||{},geometry=node.classic_display?.geometry;
  let face=wrapper.querySelector(':scope > .fx-classic-shape');
  if(!face){
    face=element('div',{class:'fx-classic-shape'});
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');face.append(svg);
  }
  const svg=face.firstElementChild;
  if(geometry){
    svg.setAttribute('viewBox',geometry.viewbox.join(' '));
    svg.setAttribute('preserveAspectRatio',p.PreserveAspectRatio?'xMidYMid meet':'none');
    let shape=svg.firstElementChild;
    if(!shape||shape.tagName!==geometry.tag){shape=document.createElementNS('http://www.w3.org/2000/svg',geometry.tag);svg.replaceChildren(shape);}
    for(const [name,value] of Object.entries(geometry.attributes||{}))shape.setAttribute(name,String(value));
    if(geometry.points)shape.setAttribute('points',geometry.points.map(point=>point.join(',')).join(' '));
    shape.setAttribute('stroke-dasharray',geometry.dash.join(' ')||'none');
    face.style.setProperty('--shape-stroke-width',String(geometry.stroke_width));
  }else svg.replaceChildren();
  const button=classicDisplayInteraction(face,node,p.AccessibleLabel||p.Tooltip||node.name);
  if(!button){
    if(p.AccessibleLabel){face.setAttribute('role','img');face.setAttribute('aria-label',p.AccessibleLabel);}
    else face.setAttribute('aria-hidden','true');
  }
  applyClassicPresentation(face,wrapper,node,node._effectiveMode);
  face.style.border='0';face.style.padding='0';
  face.style.setProperty('--shape-focus-width',String(p.BorderStyle==='None'?0:p.FocusedBorderThickness||0));
  return face;
}
