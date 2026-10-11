'use strict';
function renderModernLink(node,wrapper){
  const p=node.props||{},mode=node._effectiveMode;
  let link=wrapper.querySelector(':scope > .fx-modern-link');
  if(!link)link=element('a',{class:'fx-modern-link'});
  link.textContent=p.Text??'';
  const active=mode==='Edit'&&!!node.link_url;
  link.dataset.mode=mode;link.dataset.type=p.Type||'Default';
  if(active){link.href=node.link_url;link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('role','link');}
  else{link.removeAttribute('href');link.removeAttribute('target');link.removeAttribute('rel');if(mode==='View')link.removeAttribute('role');else link.setAttribute('role','link');}
  link.tabIndex=active?0:-1;
  if(mode==='View')link.removeAttribute('aria-disabled');else link.setAttribute('aria-disabled',String(!active));
  link.setAttribute('aria-label',p.AccessibleLabel||p.Text||node.name);
  link.lang=p.ContentLanguage||'';
  link.style.color=mode==='Disabled'?'#bdbdbd':p.Color||(mode==='View'||p.Type==='Subtle'?'#242424':p.BasePaletteColor||'#0f6cbd');
  link.style.background=p.Fill||'transparent';link.style.font='inherit';
  link.style.fontStyle=p.Italic?'italic':'normal';
  link.style.textDecoration=[p.Underline?'underline':'',p.Strikethrough?'line-through':''].filter(Boolean).join(' ')||'none';
  link.style.whiteSpace=p.Wrap===false?'nowrap':'pre-wrap';
  link.style.textAlign=(p.Align||'Left').toLowerCase();
  link.style.alignContent={Top:'start',Middle:'center',Bottom:'end'}[p.VerticalAlign]||'center';
  link.style.borderWidth=(p.BorderThickness??0)+'px';link.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();link.style.borderColor=p.BorderColor||'transparent';
  for(const corner of ['TopLeft','TopRight','BottomLeft','BottomRight'])link.style['border'+corner+'Radius']=(p['Radius'+corner]??0)+'px';
  for(const direction of ['Top','Bottom','Left','Right'])link.style['padding'+direction]=(p['Padding'+direction]??5)+'px';
  wrapper.style.padding='0px';wrapper.style.border='0px';wrapper.style.background='transparent';
  link.onclick=event=>{
    if($('inspect-toggle').checked){event.preventDefault();return;}
    if(node._effectiveMode!=='Edit'||!node.link_url)event.preventDefault();
    event.stopPropagation();
  };
  return link;
}
