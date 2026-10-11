'use strict';
function applyCanvasInputStyle(target,wrapper,p){
  target.style.fontFamily=(p.Font||'Segoe UI')+', Arial, sans-serif';
  target.style.fontSize=(p.FontSize??14)+'px';
  target.style.fontWeight={Normal:'400',Semibold:'600',Bold:'700',Lighter:'300'}[p.FontWeight]||p.FontWeight||'400';
  target.style.fontStyle=p.FontItalic?'italic':'normal';
  target.style.textDecoration=[p.FontUnderline?'underline':'',p.FontStrikethrough?'line-through':''].filter(Boolean).join(' ');
  target.style.color=p.FontColor||'#242424';
  if(target.classList.contains('fx-text-input')){
    wrapper.style.background='transparent';wrapper.style.border='';wrapper.style.padding='0';
    target.style.background=p.Fill||'';
    for(const side of ['Top','Right','Bottom','Left'])target.style['padding'+side]=p['Padding'+side]==null?'':p['Padding'+side]+'px';
  }
}
function renderCanvasCheckbox(node,wrapper,mode){
  const p=node.props||{};let root=wrapper.querySelector(':scope > .fx-canvas-checkbox');
  if(!root){
    root=element('label',{class:'fx-checkbox fx-canvas-checkbox'});
    const input=element('input',{type:'checkbox'}),label=element('span');root.append(input,label);
    input.onchange=()=>{
      const m=root._model;if(m.mode!=='Edit'||$('inspect-toggle').checked){input.checked=!!m.node.value;return;}
      emit(m.node,'OnSelect',{checked:input.checked,reset_token:m.node.check_reset});
    };
    root.onclick=e=>{if(!$('inspect-toggle').checked)e.stopPropagation();};
  }
  root._model={node,mode};const input=root.querySelector('input');
  input.checked=!!node.value;input.disabled=mode!=='Edit';
  input.setAttribute('aria-label',p.AccessibleLabel||p.Label||node.name);
  input.style.accentColor=p.BasePaletteColor||'#0f6cbd';
  input.style.width=input.style.height=(p.CheckboxSize??16)+'px';input.style.flexShrink='0';
  root.querySelector('span').textContent=p.Label??'';
  root.style.height='100%';root.style.display='flex';root.style.alignItems='center';root.style.gap='8px';
  applyCanvasInputStyle(root,wrapper,p);return root;
}
