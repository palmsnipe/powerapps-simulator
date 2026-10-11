'use strict';
// Browser layout/focus only; Python owns command selection and callbacks.
function renderToolbar(node,wrapper,mode){
 let root=wrapper.querySelector(':scope > .fx-toolbar');
 if(!root){
  root=element('div',{class:'fx-toolbar',role:'toolbar'});
  root._more=element('button',{type:'button',class:'fx-toolbar-more','aria-label':'More commands','aria-haspopup':'menu','aria-expanded':'false'},'⋯');
  root._menu=element('div',{class:'fx-toolbar-menu',role:'menu',popover:'auto','aria-label':'More commands'});
  root._more.onclick=e=>{e.stopPropagation();if($('inspect-toggle').checked)return;root._menu.togglePopover();};
  root._menu.addEventListener('toggle',e=>{root._more.setAttribute('aria-expanded',String(e.newState==='open'));if(e.newState==='open'){const rect=root._more.getBoundingClientRect();root._menu.style.left=Math.max(4,Math.min(rect.left,window.innerWidth-root._menu.offsetWidth-4))+'px';root._menu.style.top=Math.min(rect.bottom+4,window.innerHeight-root._menu.offsetHeight-4)+'px';root._menu.querySelector('button:not(:disabled)')?.focus();}});
  root._layout=()=>{
   if(!root.isConnected)return;
   const vertical=root._model.node.props?.Alignment==='Vertical',buttons=root._buttons||[],more=root._more;
   buttons.forEach(b=>b.hidden=false);more.hidden=false;
   const css=getComputedStyle(root),gap=parseFloat(css.gap)||0;
   const available=vertical?root.clientHeight-parseFloat(css.paddingTop)-parseFloat(css.paddingBottom):root.clientWidth-parseFloat(css.paddingLeft)-parseFloat(css.paddingRight);
   const size=b=>vertical?b.offsetHeight:b.offsetWidth;
   const total=buttons.reduce((n,b)=>n+size(b),0)+Math.max(0,buttons.length-1)*gap;
   let used=0,overflow=false;const hidden=[];
   for(const button of buttons){const amount=size(button)+(used?gap:0);if(total>available&&(overflow||used+amount+gap+size(more)>available)){overflow=true;button.hidden=true;hidden.push(button);}else used+=amount;}
   more.hidden=!hidden.length;
   const menuChildren=hidden.map(button=>{const item=button._command;let entry=[...root._menu.children].find(e=>e.dataset.key===item.key);if(!entry)entry=element('button',{type:'button',role:'menuitem','data-key':item.key});entry.disabled=button.disabled;entry.textContent=item.label||item.key;entry.title=item.tooltip;entry.onclick=e=>{e.stopPropagation();root._menu.hidePopover();root._more.focus();button.click();};entry.onkeydown=e=>{if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const enabled=[...root._menu.children].filter(b=>!b.disabled),i=enabled.indexOf(entry),n=e.key==='Home'?0:e.key==='End'?enabled.length-1:(i+(e.key==='ArrowDown'?1:-1)+enabled.length)%enabled.length;enabled[n]?.focus();}else if(e.key==='Escape'){root._menu.hidePopover();root._more.focus();}};return entry;});
   reconcile(root._menu,menuChildren);
   const enabled=buttons.filter(b=>!b.hidden&&!b.disabled);if(!more.hidden)enabled.push(more);
   const active=enabled.find(b=>b.dataset.key===root._focusKey)||enabled[0];
   buttons.forEach(b=>b.tabIndex=!b.hidden&&!b.disabled&&root._model.node.tab_stop!==false&&b===active?0:-1);more.tabIndex=root._model.node.tab_stop!==false&&more===active?0:-1;
  };
  root._resize=new ResizeObserver(()=>{if(!root.isConnected)root._resize.disconnect();else root._layout();});root._resize.observe(root);
 }
 const p=node.props||{},vertical=p.Alignment==='Vertical';root._model={node,mode};root.setAttribute('aria-label',p.AccessibleLabel||node.name);root.setAttribute('aria-orientation',vertical?'vertical':'horizontal');
 root.dataset.padding=p.Padding||'Medium';root.dataset.layout=p.Layout||'Icon before';root.style.flexDirection=vertical?'column':'row';root.style.fontFamily=p.Font||'Segoe UI, sans-serif';root.style.fontSize=(p.FontSize??14)+'px';root.style.fontWeight=({Normal:'400',Semibold:'600',Bold:'700',Lighter:'300'}[p.FontWeight]||p.FontWeight||'normal');root.style.fontStyle=p.FontItalic?'italic':'normal';root.style.textDecoration=[p.FontUnderline?'underline':'',p.FontStrikethrough?'line-through':''].filter(Boolean).join(' ');root.style.color=p.FontColor||'inherit';root.style.setProperty('--toolbar-palette',p.BasePaletteColor||'#0f6cbd');
 root.onkeydown=e=>{if($('inspect-toggle').checked)return;const previous=vertical?'ArrowUp':'ArrowLeft',next=vertical?'ArrowDown':'ArrowRight';if(![previous,next,'Home','End'].includes(e.key))return;e.preventDefault();e.stopPropagation();const enabled=[...root.children].filter(b=>b.tagName==='BUTTON'&&!b.hidden&&!b.disabled),at=enabled.indexOf(document.activeElement),i=e.key==='Home'?0:e.key==='End'?enabled.length-1:(at+(e.key===next?1:-1)+enabled.length)%enabled.length;enabled[i]?.focus();};
 const children=(node.commands||[]).map(item=>{
  const identity=JSON.stringify([!!item.invalid,item.invalid?item.index:item.key]);let button=[...root.children].find(b=>b.dataset.identity===identity);if(!button)button=element('button',{type:'button','data-key':item.key,'data-identity':identity});
  button._command=item;button.disabled=mode!=='Edit'||item.disabled;button.tabIndex=-1;button.dataset.appearance=item.appearance;button.title=item.tooltip||(p.Layout==='Icon only'?item.label:'');button.setAttribute('aria-label',item.label||item.key);button.setAttribute('aria-pressed',String((node.selection||[]).includes(item.key)));button.style.font='inherit';
  const parts=[],text=element('span',{class:'fx-toolbar-label'},item.label),icon=item.icon?iconGlyph(item.icon):null;
  if(p.Layout==='Text only'||!icon)parts.push(text);else if(p.Layout==='Icon only')parts.push(icon);else if(p.Layout==='Icon after')parts.push(text,icon);else parts.push(icon,text);
  reconcile(button,parts);button.onclick=e=>{if($('inspect-toggle').checked||button.disabled)return;e.stopPropagation();const m=root._model;emit(m.node,'OnSelect',{key:item.key,option_token:m.node.option_token});};
  button.onfocus=()=>{root._focusKey=item.key;root._layout();};return button;
 });
 root._more.onfocus=()=>{root._focusKey=undefined;children.forEach(b=>b.tabIndex=-1);root._more.tabIndex=node.tab_stop!==false?0:-1;};
 root._buttons=children;reconcile(root,[...children,root._more,root._menu]);root._layout();return root;
}
