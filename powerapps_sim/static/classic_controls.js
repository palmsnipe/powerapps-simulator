'use strict';
// Classic visuals share state colors; formulas and selection remain on Python.
function applyClassicPresentation(face,wrapper,node,mode){
  const p=node.props||{};face.classList.add('fx-classic-face');face.dataset.mode=mode;
  face.style.color='';face.style.background='';face.style.borderColor='';
  for(const [key,value] of Object.entries({color:p.Color,fill:p.Fill,border:p.BorderColor,'hover-color':p.HoverColor,'hover-fill':p.HoverFill,'hover-border':p.HoverBorderColor,'pressed-color':p.PressedColor,'pressed-fill':p.PressedFill,'pressed-border':p.PressedBorderColor,'disabled-color':p.DisabledColor,'disabled-fill':p.DisabledFill,'disabled-border':p.DisabledBorderColor,'focus-color':p.FocusedBorderColor}))face.style.setProperty('--classic-'+key,value||'transparent');
  face.style.setProperty('--classic-focus-width',(p.FocusedBorderThickness||0)+'px');
  face.style.borderWidth=(p.BorderThickness||0)+'px';face.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();
  for(const direction of ['Top','Bottom','Left','Right'])face.style['padding'+direction]=(p['Padding'+direction]||0)+'px';
  face.style.borderRadius=['RadiusTopLeft','RadiusTopRight','RadiusBottomRight','RadiusBottomLeft'].map(k=>(p[k]||0)+'px').join(' ');
  wrapper.style.background='transparent';wrapper.style.border='0';wrapper.style.padding='0';
}
function renderClassicCheckbox(node,wrapper,mode){
  const p=node.props||{};
  let label=wrapper.querySelector(':scope > .fx-classic-checkbox');
  if(!label){label=element('label',{class:'fx-classic-checkbox'});label.append(element('input',{type:'checkbox'}),element('span'));}
  const input=label.querySelector('input'),caption=label.querySelector('span');
  input.checked=!!node.value;input.disabled=mode!=='Edit';
  input.setAttribute('aria-label',p.AccessibleLabel||p.Text||node.name);
  input.style.width=input.style.height=(p.CheckboxSize??40)+'px';
  input.style.setProperty('--classic-check-background',p.CheckboxBackgroundFill||'transparent');
  input.style.setProperty('--classic-check-border',p.CheckboxBorderColor||'transparent');
  input.style.setProperty('--classic-checkmark',p.CheckmarkFill||'transparent');
  caption.textContent=p.Text||'';
  label.style.alignItems=({Top:'flex-start',Middle:'center',Bottom:'flex-end'}[p.VerticalAlign]||'center');
  label.onclick=e=>{if($('inspect-toggle').checked)e.preventDefault();};
  input.onchange=()=>{if(mode==='Edit'&&!$('inspect-toggle').checked)emit(node,'OnChange',{checked:input.checked,reset_token:node.check_reset});};
  applyClassicPresentation(label,wrapper,node,mode);
  return label;
}
function renderClassicToggle(node,wrapper,mode){
  const p=node.props||{};let root=wrapper.querySelector(':scope > .fx-classic-toggle');
  if(!root){root=element('label',{class:'fx-classic-toggle'});root.append(element('input',{type:'checkbox',role:'switch'}),element('span'));}
  const input=root.querySelector('input'),caption=root.querySelector('span');input.checked=!!node.value;input.disabled=mode!=='Edit';input.setAttribute('aria-label',p.AccessibleLabel||node.name);
  caption.textContent=node.value?p.TrueText:p.FalseText;caption.hidden=!p.ShowLabel;caption.style.paddingLeft=(p.LabelPaddingLeft??5)+'px';caption.style.paddingRight=(p.LabelPaddingRight??5)+'px';root.style.flexDirection=p.TextPosition==='Left'?'row-reverse':'row';
  input.style.setProperty('--toggle-rail',node.value?p.TrueFill:p.FalseFill);input.style.setProperty('--toggle-hover',node.value?p.TrueHoverFill:p.FalseHoverFill);input.style.setProperty('--toggle-handle',p.HandleFill);
  root.onclick=e=>{if($('inspect-toggle').checked)e.preventDefault();};input.onchange=()=>{if(mode==='Edit'&&!$('inspect-toggle').checked)emit(node,'OnChange',{checked:input.checked,reset_token:node.check_reset});};applyClassicPresentation(root,wrapper,node,mode);return root;
}
function renderClassicSlider(node,wrapper,mode){
  const p=node.props||{};let root=wrapper.querySelector(':scope > .fx-classic-slider');
  if(!root){root=element('div',{class:'fx-classic-slider'});root.append(element('input',{type:'range'}),element('output'));}
  const input=root.querySelector('input'),output=root.querySelector('output');input.min=p.Min;input.max=p.Max;input.step='any';input.value=node.value;input.disabled=mode!=='Edit'||p.ReadOnly;input.setAttribute('aria-label',p.AccessibleLabel||node.name);
  const vertical=p.Layout==='Vertical';root.dataset.vertical=String(vertical);input.style.writingMode=vertical?'vertical-lr':'horizontal-tb';input.style.direction=vertical?'rtl':'ltr';input.setAttribute('aria-orientation',vertical?'vertical':'horizontal');
  root.style.setProperty('--slider-rail',p.RailFill);root.style.setProperty('--slider-value',p.ValueFill);root.style.setProperty('--slider-hover-rail',p.RailHoverFill);root.style.setProperty('--slider-hover-value',p.ValueHoverFill);root.style.setProperty('--slider-handle',p.HandleFill);root.style.setProperty('--slider-hover-handle',p.HandleHoverFill);root.style.setProperty('--slider-active-handle',p.HandleActiveFill);root.style.setProperty('--slider-size',(p.HandleSize??24)+'px');root.style.setProperty('--slider-thickness',(p.RailThickness??3)+'px');
  const ratio=p.Max===p.Min?0:100*(node.value-p.Min)/(p.Max-p.Min);input.style.setProperty('--slider-progress',ratio+'%');output.textContent=node.value;output.hidden=!p.ShowValue;
  const send=name=>{if(mode==='Edit'&&!p.ReadOnly&&!$('inspect-toggle').checked)emit(node,name,{value:Number(input.value),reset_token:node.input_reset});};input.oninput=()=>send('OnInput');input.onchange=()=>send('OnChange');input.onclick=e=>{if(!$('inspect-toggle').checked){e.stopPropagation();if(mode==='Edit'&&!p.ReadOnly)emit(node,'OnSelect');}};applyClassicPresentation(root,wrapper,node,mode);return root;
}
