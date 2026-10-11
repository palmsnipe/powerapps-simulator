'use strict';
let listBoxId=0;
function renderListBox(node,wrapper,mode){
  const p=node.props||{};let root=wrapper.querySelector(':scope > .fx-listbox');
  if(!root){
    root=element('div',{class:'fx-listbox',role:'listbox',tabindex:'0'});root._id='emu-list-'+(++listBoxId);root._active=0;
    root._select=(operation,index)=>{const m=root._model;if(m.mode!=='Edit'||$('inspect-toggle').checked)return;emit(m.node,'OnChange',{operation,index,option_token:m.node.option_token});};
    root.onkeydown=e=>{
      const m=root._model,opts=m.node.options||[];if($('inspect-toggle').checked||m.mode==='Disabled'||!opts.length)return;
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'&&m.p.SelectMultiple){e.preventDefault();root._select('all');return;}
      if([' ','Enter'].includes(e.key)){e.preventDefault();root._select(m.p.SelectMultiple?'toggle':'replace',opts[root._active]?.index);return;}
      if(['ArrowDown','ArrowUp','Home','End','PageDown','PageUp'].includes(e.key)){
        e.preventDefault();const step=e.key==='ArrowUp'||e.key==='PageUp'?-1:1;
        const jump=e.key.startsWith('Page')?Math.max(1,Math.floor(root.clientHeight/Math.max(1,(m.p.Size||13)*(m.p.LineHeight??1.2)))):1;
        let i=e.key==='Home'?0:e.key==='End'?opts.length-1:Math.max(0,Math.min(opts.length-1,root._active+step*jump));
        while(opts[i]?.disabled&&i+step>=0&&i+step<opts.length)i+=step;
        root._active=i;root._highlight();
        if(m.mode==='Edit'&&!opts[i]?.disabled){if(e.shiftKey&&m.p.SelectMultiple)root._select('range',opts[i].index);else if(!m.p.SelectMultiple)root._select('replace',opts[i].index);}
      }else if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
        root._typeahead=(Date.now()-(root._typeTime||0)<800?root._typeahead||'':'')+e.key.toLowerCase();root._typeTime=Date.now();
        const i=opts.findIndex(o=>!o.disabled&&o.label.toLowerCase().startsWith(root._typeahead));
        if(i>=0){root._active=i;root._highlight();if(!m.p.SelectMultiple)root._select('replace',opts[i].index);}
      }
    };
    root._highlight=()=>{[...root.children].forEach((e,i)=>e.classList.toggle('highlighted',i===root._active));const active=root.children[root._active];if(active){root.setAttribute('aria-activedescendant',active.id);active.scrollIntoView({block:'nearest'});}else root.removeAttribute('aria-activedescendant');};
  }
  root._model={node,p,mode};root.dataset.mode=mode;
  if(root._reset!==node.list_reset){root._reset=node.list_reset;root._active=Math.max(0,(node.options||[]).findIndex(o=>(node.selection||[]).includes(o.index)));}
  root._active=Math.min(root._active,Math.max(0,(node.options||[]).length-1));
  root.setAttribute('aria-label',p.AccessibleLabel||node.name);root.setAttribute('aria-multiselectable',String(!!p.SelectMultiple));
  root.setAttribute('aria-disabled',String(mode==='Disabled'));root.setAttribute('aria-readonly',String(mode==='View'));
  applyClassicPresentation(root,wrapper,node,mode);
  root.style.setProperty('--list-selection-fill',p.SelectionFill||'#0f6cbd');root.style.setProperty('--list-selection-color',p.SelectionColor||'white');
  const options=(node.options||[]).map((o,i)=>{
    let option=[...root.children].find(c=>c.dataset.index===String(o.index));
    if(!option)option=element('div',{role:'option','data-index':o.index,id:root._id+'-'+o.index});
    option.textContent=o.label;option.setAttribute('aria-selected',String((node.selection||[]).includes(o.index)));option.setAttribute('aria-disabled',String(!!o.disabled));
    option.style.lineHeight=String(p.LineHeight??1.2);option.style.paddingLeft=(p.ItemPaddingLeft??10)+'px';
    option.onpointerdown=e=>{if(mode!=='Disabled')e.preventDefault();};
    option.onclick=e=>{if(root._model.mode!=='Edit'||o.disabled||$('inspect-toggle').checked)return;root._active=i;root.focus({preventScroll:true});root._select(e.shiftKey&&p.SelectMultiple?'range':p.SelectMultiple?'toggle':'replace',o.index);};
    option.classList.toggle('highlighted',i===root._active);return option;
  });
  reconcile(root,options);root.setAttribute('aria-activedescendant',options[root._active]?.id||'');
  return root;
}
