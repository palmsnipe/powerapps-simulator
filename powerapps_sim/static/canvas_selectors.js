/* Archived DropdownCanvas uses a native desktop select. */
function renderCanvasDropdown(node,wrapper,mode){
  let input=[...wrapper.children].find(e=>e.classList.contains('fx-canvas-dropdown'));
  if(!input){input=element('select',{class:'fx-input fx-canvas-dropdown'});input.onchange=()=>{const m=input._model;if(m.mode!=='Edit'||$('inspect-toggle').checked)return;emit(m.node,'OnChange',{indices:input.value===''?[]:[Number(input.value)],option_token:m.node.option_token});};}
  input._model={node,mode};const p=node.props||{};
  const options=[element('option',{value:''},'')].concat((node.options||[]).map(o=>{const option=element('option',{value:String(o.index)},o.label);option.disabled=!!o.disabled;return option;}));
  if(!node.selection?.length&&node.selected_labels?.length){const retained=element('option',{value:'retained'},node.selected_labels[0]);retained.disabled=true;options.push(retained);}
  input.replaceChildren(...options);input.value=node.selection?.length?String(node.selection[0]):node.selected_labels?.length?'retained':'';
  input.disabled=mode!=='Edit';input.setAttribute('aria-label',p.AccessibleLabel||node.name);input.setAttribute('aria-required',String(!!p.Required));input.setAttribute('aria-invalid',String(p.ValidationState==='Error'||!!p.Required&&!node.selected_labels?.length));
  applyCanvasSelectorStyle(input,wrapper,p);return input;
}

function applyCanvasSelectorStyle(target,wrapper,p){
  applyCanvasInputStyle(target,wrapper,p);wrapper.style.background='transparent';wrapper.style.border='';wrapper.style.padding='0';
  target.style.borderRadius=(p.BorderRadius??4)+'px';target.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();target.style.borderWidth=(p.BorderThickness??1)+'px';target.style.borderColor=p.BorderColor||'#d1d1d1';
  target.style.background=p.Fill||({FilledDarker:'#f5f5f5',FilledLighter:'#fff',Outline:'transparent'}[p.Appearance]||'#f5f5f5');
  for(const side of ['Top','Right','Bottom','Left'])target.style['padding'+side]=p['Padding'+side]==null?'':p['Padding'+side]+'px';
}
