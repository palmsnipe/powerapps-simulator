'use strict';
// Preserve each tab button across server updates; selection stays in Python.
function renderTabList(node,wrapper,mode){
  let root=wrapper.querySelector(':scope > .fx-tablist');
  if(!root)root=element('div',{class:'fx-tablist',role:'tablist'});
  const p=node.props||{},authored=new Set(node.tab_contract?.authored||[]);
  const archived=node.tab_contract?.family==='TabList';
  const vertical=(archived||node.tab_contract?.version==='1.0.2')&&p.Alignment==='Vertical';
  root._model={node,mode};root.setAttribute('aria-label',p.AccessibleLabel||node.name);
  root.setAttribute('aria-orientation',vertical?'vertical':'horizontal');
  root.dataset.appearance=p.Appearance||'Transparent';root.dataset.tabSize=(archived?p.Size:p.TabSize)||'Medium';
  root.dataset.archived=String(archived);
  root.style.overflow=archived?'auto':'hidden';
  if(archived){
    root.style.fontFamily=p.Font||'Segoe UI, sans-serif';root.style.fontSize=(p.FontSize||14)+'px';
    root.style.fontWeight=({Normal:'400',Semibold:'600',Bold:'700',Lighter:'300'}[p.FontWeight]||p.FontWeight||'normal');
    root.style.setProperty('--tab-palette',p.BasePaletteColor||'#0f6cbd');
  }else{
    root.style.fontFamily='inherit';root.style.fontSize='inherit';root.style.fontWeight='inherit';
    root.style.removeProperty('--tab-palette');
  }
  root.style.flexDirection=vertical?'column':'row';
  root.style.justifyContent=vertical?'flex-start':({Start:'flex-start',Center:'center',End:'flex-end'}[p.Alignment]||'flex-start');
  root.style.alignItems=vertical?'flex-start':'center';
  const selected=(node.selection||[])[0],first=(node.options||[]).find(o=>!o.disabled)?.index;
  const children=(node.options||[]).map(o=>{
    let button=[...root.children].find(e=>e.dataset.index===String(o.index));
    if(!button)button=element('button',{type:'button',role:'tab','data-index':o.index});
    const active=o.index===selected;
    button.textContent=o.label;button.setAttribute('aria-selected',String(active));
    button.disabled=mode!=='Edit'||!!o.disabled;
    button.tabIndex=node.tab_stop!==false&&!button.disabled&&o.index===(selected??first)?0:-1;
    button.style.font='inherit';button.style.fontStyle=(archived?p.FontItalic:p.Italic)?'italic':'normal';
    button.style.textDecoration=[(archived?p.FontUnderline:p.Underline)?'underline':'',(archived?p.FontStrikethrough:p.Strikethrough)?'line-through':''].filter(Boolean).join(' ');
    button.style.textAlign=({Left:'left',Center:'center',Right:'right'}[p.Align]||'center');
    button.style.color=archived?(p.FontColor||(active?'var(--tab-palette)':'inherit')):authored.has('Color')?p.Color||'inherit':active?'#0f6cbd':p.FontColor||p.Color||'inherit';
    if(authored.has('BorderThickness'))button.style.borderWidth=(p.BorderThickness??0)+'px';else button.style.removeProperty('border-width');
    if(authored.has('BorderStyle'))button.style.borderStyle=(p.BorderStyle||'None').toLowerCase();else button.style.removeProperty('border-style');
    if(authored.has('BorderColor'))button.style.borderColor=p.BorderColor||'transparent';else button.style.removeProperty('border-color');
    for(const corner of ['TopLeft','TopRight','BottomLeft','BottomRight']){
      const key='Radius'+corner,css='border'+corner+'Radius';
      if(authored.has(key))button.style[css]=(p[key]??0)+'px';else button.style[css]='';
    }
    for(const side of ['Top','Bottom','Left','Right']){
      if(authored.has('Padding'+side))button.style['padding'+side]=(p['Padding'+side]??0)+'px';else button.style['padding'+side]='';
    }
    button.onclick=e=>{if($('inspect-toggle').checked||button.disabled)return;e.stopPropagation();const m=root._model;emit(m.node,'OnChange',{indices:[o.index],option_token:m.node.option_token});};
    button.onkeydown=e=>{
      if($('inspect-toggle').checked||button.disabled)return;
      const previous=vertical?'ArrowUp':'ArrowLeft',next=vertical?'ArrowDown':'ArrowRight';
      if(![previous,next,'Home','End'].includes(e.key))return;
      e.preventDefault();const enabled=[...root.children].filter(b=>!b.disabled),at=enabled.indexOf(button);
      const i=e.key==='Home'?0:e.key==='End'?enabled.length-1:(at+(e.key===next?1:-1)+enabled.length)%enabled.length;
      enabled[i]?.focus();
    };
    return button;
  });
  reconcile(root,children);
  // Padding/borders belong to each tab, not both the control and its children.
  wrapper.style.padding='0px';wrapper.style.border='0px';
  return root;
}
