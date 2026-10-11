'use strict';
// Draft text and timer scheduling live in the browser; Power Fx stays on Python.
function renderModernTextInput(node, wrapper, mode){
  const classic=node.family==='Classic/TextInput',canvas=node.family==='TextInput';
  const p=classic?{...node.props,TriggerOutput:node.props.DelayOutput?'Delayed':'Keypress',Placeholder:node.props.HintText}:node.props||{}, multiline=p.Type==='Multiline'||p.Mode==='MultiLine'||canvas&&p.Mode==='Multiline';
  const tag=multiline?'TEXTAREA':'INPUT';
  let input=wrapper.querySelector(':scope > .fx-text-input, :scope > .fx-classic-text > .fx-text-input');
  if(input&&input.tagName!==tag){input._cancel();input.remove();input=null;}
  const oldServer=input?input._server:String(node.value??'');
  const server=node.value===undefined?oldServer:String(node.value??'');
  if(!input){
    input=element(tag.toLowerCase(),{class:'fx-input fx-text-input'});
    input._draft=server;input._server=server;input._reset=node.text_reset??0;
    input._cancel=()=>{clearTimeout(input._timer);input._timer=null;};
    input._send=name=>{
      input._cancel();const value=input._draft,reset=input._reset;
      enqueue(async()=>{
        if(!input.isConnected||input._reset!==reset||input._model.mode!=='Edit')return;
        if(name==='OnInput'&&input._draft!==value)return;
        state=await api('/api/event',{path:input._model.node.path,name,value:{text:value,reset_token:reset}});
        renderState();if(selectedPath)await inspect(selectedPath);
      });
    };
    input.oninput=()=>{
      if(input._model.mode!=='Edit'||$('inspect-toggle').checked)return;
      input._draft=input.value;input._cancel();
      const trigger=input._model.p.TriggerOutput;
      if(trigger==='Delayed')input._timer=setTimeout(()=>input._send('OnInput'),500);
      else if(trigger==='Keypress')input._send('OnInput');
    };
    input.onblur=()=>{if(input._model.mode==='Edit'&&!$('inspect-toggle').checked)input._send('OnChange');};
    input.onclick=event=>{
      if($('inspect-toggle').checked)return;
      event.stopPropagation();if(input._model.mode==='Edit'&&input._model.node.family!=='TextInput')emit(input._model.node,'OnSelect');
    };
  }
  input._model={node,p,mode};
  const reset=node.text_reset??input._reset;
  if(input._reset!==reset){input._cancel();input._reset=reset;input._draft=server;}
  else if(input._draft===oldServer)input._draft=server;
  input._server=server;
  if(mode!=='Edit'){input._cancel();input._draft=server;}
  if(input.value!==input._draft)input.value=input._draft;
  if(input.tagName==='INPUT')input.type=p.Type==='Password'||p.Mode==='Password'?'password':({Search:'search',Email:'email',Telephone:'tel',URL:'url'}[p.Type]||'text');
  input.disabled=mode==='Disabled'||mode==='Hidden';input.readOnly=mode==='View';
  input.placeholder=p.Placeholder||p.InputTextPlaceholder||'';
  input.setAttribute('aria-label',p.AccessibleLabel||node.name);
  input.setAttribute('aria-required',String(!!p.Required));
  const invalid=p.ValidationState==='Error'||p.Required&&server==='';
  input.setAttribute('aria-invalid',String(!!invalid));input.classList.toggle('invalid',!!invalid);
  if(p.MaxLength>0||canvas&&p.MaxLength===0)input.maxLength=p.MaxLength;else input.removeAttribute('maxlength');
  input.style.textAlign=({Left:'left',Start:'start',End:'end',Center:'center',Right:'right',Justify:'justify'}[p.Align]||'left');
  input.dataset.appearance=p.Appearance||'FilledDarker';
  input.style.borderColor=invalid?'#c50f1f':p.BorderColor||'';
  input.style.borderStyle=p.BorderStyle?.toLowerCase()||'solid';
  input.style.borderWidth=p.BorderThickness>0?p.BorderThickness+'px':'';
  input.style.borderRadius=['RadiusTopLeft','RadiusTopRight','RadiusBottomRight','RadiusBottomLeft'].map(k=>(p[k]||0)+'px').join(' ');
  if(canvas){
    input.style.borderRadius=p.BorderRadius==null?'':p.BorderRadius+'px';
    applyCanvasInputStyle(input,wrapper,p);
  }
  wrapper._cleanup=input._cancel;
  if(classic){
    input.spellcheck=!!p.EnableSpellCheck;
    input.inputMode=p.VirtualKeyboardMode==='Numeric'||p.VirtualKeyboardMode==='Auto'&&p.Format==='Number'?'decimal':'text';
    input.style.lineHeight=p.LineHeight||1.2;
    applyClassicPresentation(input,wrapper,node,mode);
    let root=wrapper.querySelector(':scope > .fx-classic-text');
    if(!root)root=element('div',{class:'fx-classic-text'});
    let clear=root.querySelector('.fx-classic-clear');
    if(!clear){clear=element('button',{type:'button',class:'fx-classic-clear',tabindex:'-1'},'×');clear.onmousedown=e=>e.preventDefault();}
    clear.setAttribute('aria-label','Clear '+(p.AccessibleLabel||node.name));clear.hidden=!p.Clear||p.Mode!=='SingleLine'||!input._draft||mode!=='Edit';
    clear.onclick=event=>{if(mode!=='Edit'||$('inspect-toggle').checked)return;event.stopPropagation();input.value='';input.oninput();input.focus();};
    reconcile(root,[input,clear]);return root;
  }
  return input;
}
