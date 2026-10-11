'use strict';
// Pointer/keyboard presentation only: the server validates values and executes FX.
function renderModernRating(node,wrapper,mode){
  let root=wrapper.querySelector(':scope > .fx-rating');
  if(!root)root=element('div',{class:'fx-rating'});
  const spec=node.rating,p=node.props||{};
  root._model={node,mode};root.dataset.mode=mode;
  root.setAttribute('role','slider');root.setAttribute('aria-label',p.AccessibleLabel||node.name);
  root.setAttribute('aria-valuemin','0');root.setAttribute('aria-valuemax',String(spec?.max??5));
  root.setAttribute('aria-valuenow',String(node.value??0));root.setAttribute('aria-valuetext',`${node.value??0} / ${spec?.max??5}`);
  root.setAttribute('aria-disabled',String(mode==='Disabled'));root.setAttribute('aria-readonly',String(mode!=='Edit'));
  root.tabIndex=mode==='Edit'?0:-1;root.style.color=p.Color||'#0f6cbd';
  const commit=value=>{const m=root._model;if(m.mode==='Edit'&&!$('inspect-toggle').checked&&m.node.rating)emit(m.node,'OnChange',{value,reset_token:m.node.input_reset});};
  root.onclick=event=>{
    if($('inspect-toggle').checked)return;
    event.stopPropagation();if(root._model.mode!=='Edit')return;
    const icon=event.target.closest('.fx-rating-item');if(!icon||!root.contains(icon))return;
    const rect=icon.getBoundingClientRect(),s=root._model.node.rating;
    commit(Number(icon.dataset.index)+(s.step===.5&&event.clientX<rect.x+rect.width/2 ? .5 : 1));root.focus();
  };
  root.onkeydown=event=>{
    const m=root._model,s=m.node.rating;if(!s||m.mode!=='Edit'||$('inspect-toggle').checked)return;
    const delta=({'ArrowRight':1,'ArrowUp':1,'ArrowLeft':-1,'ArrowDown':-1})[event.key];
    if(delta!==undefined||['Home','End'].includes(event.key)){
      event.preventDefault();event.stopPropagation();
      emit(m.node,'OnChange',{key:event.key,reset_token:m.node.input_reset});
    }
  };
  const children=[];
  if(spec?.glyph)for(let i=0;i<spec.max;i++){
    let item=[...root.children].find(e=>e.dataset.index===String(i));
    if(!item){item=element('span',{class:'fx-rating-item','data-index':i,'aria-hidden':'true'});const empty=iconGlyph(spec.glyph),filled=element('span',{class:'fx-rating-filled'});empty.classList.add('fx-rating-empty');filled.append(iconGlyph(spec.glyph));item.append(empty,filled);item.dataset.glyph=spec.glyph.symbol;}
    if(item.dataset.glyph!==spec.glyph.symbol){item.replaceChildren();const empty=iconGlyph(spec.glyph),filled=element('span',{class:'fx-rating-filled'});empty.classList.add('fx-rating-empty');filled.append(iconGlyph(spec.glyph));item.append(empty,filled);item.dataset.glyph=spec.glyph.symbol;}
    item.querySelector('.fx-rating-filled').style.clipPath='inset(0 '+((1-Math.max(0,Math.min(1,(node.value??0)-i)))*100)+'% 0 0)';children.push(item);
  }
  reconcile(root,children);return root;
}

// Fluent V8 exposes an authored/bound Value and radio-style star interaction.
function renderFluentRating(node,wrapper,mode){
  let root=wrapper.querySelector(':scope > .fx-fluent-rating');
  if(!root)root=element('div',{class:'fx-fluent-rating'});
  const p=node.props||{},spec=node.fluent_rating,editable=mode==='Edit',maximum=spec?.max??5;
  root._model={node,mode};root.dataset.mode=mode;
  root.setAttribute('role',mode==='View'?'textbox':'radiogroup');root.setAttribute('aria-label',p.AccessibleLabel||node.name);
  root.setAttribute('aria-disabled',String(mode==='Disabled'));root.setAttribute('aria-readonly',String(!editable));
  root.tabIndex=mode==='View'&&node.tab_stop!==false?0:-1;
  root.style.setProperty('--rating-checked',p.CheckedFill||'#0078d4');root.style.setProperty('--rating-unchecked',p.UncheckedFill||'#605e5c');
  root.style.setProperty('--rating-hover',p.HoverFill||p.CheckedFill||'#0078d4');root.style.setProperty('--rating-disabled',p.DisabledFill||'#a19f9d');
  root.style.paddingBlockStart=(p.PaddingTop??0)+'px';root.style.paddingBlockEnd=(p.PaddingBottom??0)+'px';
  root.style.paddingInlineStart=(p.PaddingStart??0)+'px';root.style.paddingInlineEnd=(p.PaddingEnd??0)+'px';
  const current=Math.max(1,Math.ceil(node.value??0)),hadFocus=root.contains(document.activeElement),pending=root._keyboardPending;
  const children=[];
  if(spec?.glyph)for(let i=1;i<=maximum;i++){
    let button=[...root.children].find(el=>el.dataset.star===String(i));
    if(!button){button=element('button',{type:'button',role:'radio',class:'fx-fluent-rating-star','data-star':i});const back=iconGlyph(spec.glyph),front=element('span',{class:'fx-fluent-rating-front','aria-hidden':'true'});back.classList.add('fx-fluent-rating-back');front.append(iconGlyph(spec.glyph));button.append(back,front);}
    button.disabled=!editable;button.tabIndex=editable&&node.tab_stop!==false&&i===current?0:-1;
    button.setAttribute('aria-label',`${p.AccessibleLabel||node.name} ${i} of ${maximum}`);button.setAttribute('aria-checked',String(i===Math.ceil(node.value??0)));
    button.setAttribute('aria-hidden',String(mode==='View'));button.style.width=(p.Size??20)+'px';button.style.height=(p.Size??20)+'px';
    button.querySelector('.fx-fluent-rating-front').style.clipPath=`inset(0 ${(1-Math.max(0,Math.min(1,(node.value??0)-i+1)))*100}% 0 0)`;
    button.onmousedown=event=>{if(node.tab_stop===false)event.preventDefault();};
    button.onclick=event=>{if($('inspect-toggle').checked)return;event.stopPropagation();const m=root._model;if(m.mode==='Edit')emit(m.node,'OnSelect',{value:i,reset_token:m.node.input_reset});};
    button.onkeydown=event=>{const m=root._model;if(m.mode!=='Edit'||$('inspect-toggle').checked)return;if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End','PageUp','PageDown'].includes(event.key)){event.preventDefault();event.stopPropagation();root._keyboardPending=true;emit(m.node,'OnChange',{key:event.key,reset_token:m.node.input_reset});}};
    children.push(button);
  }
  reconcile(root,children);
  if(pending&&hadFocus&&editable&&node.tab_stop!==false){root._keyboardPending=false;children.find(b=>Number(b.dataset.star)===current)?.focus({preventScroll:true});}
  return root;
}
