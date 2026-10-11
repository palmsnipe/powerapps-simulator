'use strict';
// Local presentation; authenticated instance events execute in Python.
function renderCanvasScalar(node,wrapper,mode){
  const p=node.props||{},slider=node.family==='Slider';
  let root=wrapper.querySelector(':scope > .fx-canvas-scalar');
  if(!root||root.dataset.family!==node.family){
    root=element(slider?'div':'label',{class:'fx-canvas-scalar'});
    root.dataset.family=node.family;
    const input=element('input',{type:slider?'range':'checkbox'});root.append(input);
    if(!slider){input.setAttribute('role','switch');root.append(element('span'));}
    root.onclick=e=>{if(!$('inspect-toggle').checked)e.stopPropagation();};
    input.oninput=()=>{const m=root._model;if(slider&&m.mode==='Edit'&&!$('inspect-toggle').checked)emit(m.node,'OnInput',{value:Number(input.value),reset_token:m.node.input_reset});};
    input.onchange=()=>{
      const m=root._model;if(m.mode!=='Edit'||$('inspect-toggle').checked)return;
      emit(m.node,slider?'OnChange':'OnSelect',{[slider?'value':'checked']:slider?Number(input.value):input.checked,reset_token:m.node.input_reset});
    };
  }
  root._model={node,mode};const input=root.querySelector('input');
  input.disabled=mode!=='Edit';input.tabIndex=Number(p.TabIndex??0);
  input.setAttribute('aria-label',p.AccessibleLabel||p.Label||node.name);
  input.title=p.Tooltip||'';input.style.accentColor=p.BasePaletteColor||'#0f6cbd';
  wrapper.style.background='transparent';wrapper.style.padding='0';
  root.style.width=root.style.height='100%';root.style.display='flex';root.style.alignItems='center';root.style.gap='8px';
  if(slider){
    input.min=p.Min??0;input.max=p.Max??100;input.step='any';
    const current=String(node.value??input.min);if(input.value!==current)input.value=current;
    const vertical=p.Layout==='Vertical';input.style.writingMode=vertical?'vertical-lr':'horizontal-tb';input.style.direction=vertical?'rtl':'ltr';
    input.setAttribute('aria-orientation',vertical?'vertical':'horizontal');
    input.style.width='100%';input.style.height=vertical?'100%':p.Size==='Small'?'20px':'32px';input.style.margin='0';
  }else{
    input.checked=!!node.value;input.setAttribute('aria-checked',String(input.checked));
    input.style.setProperty('--toggle-color',p.BasePaletteColor||'#0f6cbd');input.style.setProperty('--toggle-width',(p.ToggleSize??40)+'px');
    root.style.flexDirection={Before:'row-reverse',Above:'column'}[p.LabelPosition]||'row';
    root.style.justifyContent=p.LabelPosition==='Before'?'flex-end':'flex-start';
    root.querySelector('span').textContent=p.Label??'Label';applyCanvasInputStyle(root,wrapper,p);
  }
  return root;
}
