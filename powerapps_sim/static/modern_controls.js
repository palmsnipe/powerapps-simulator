'use strict';
// Presentation and keyboard handling only; Python owns selection and callbacks.
let modernControlId=0, activeDropdown=null;
function settleModernControls(){if(activeDropdown&&(!activeDropdown.isConnected||activeDropdown.closest('[hidden]'))){activeDropdown._cancel?.();activeDropdown._close();}}
function renderModernSelector(node,wrapper,mode){
  const disabled=mode!=='Edit';
  const p=node.props||{},radio=['Radio','ModernRadio','Classic/Radio'].includes(node.family),classic=node.family==='Classic/DropDown';
  const cls=radio?'fx-radio':'fx-dropdown';
  let root=[...wrapper.children].find(e=>e.classList.contains(cls));
  if(!root)root=element('div',{class:cls});
  root._model={node,p,disabled,mode};
  root.dataset.mode=mode;
  if(radio){
    const classicRadio=node.family==='Classic/Radio';
    const nativeRadio=node.family==='Radio',stacked=nativeRadio&&p.Layout==='Horizontal Stacked';
    if(nativeRadio)applyCanvasInputStyle(root,wrapper,p);
    if(classicRadio){
      applyClassicPresentation(root,wrapper,node,mode);
      root.style.setProperty('--classic-radio-border',p.RadioBorderColor||'transparent');
      root.style.setProperty('--classic-radio-background',p.RadioBackgroundFill||'transparent');
      root.style.setProperty('--classic-radio-selection',p.RadioSelectionFill||'transparent');
    }
    root.setAttribute('role','radiogroup');
    root.setAttribute('aria-label',p.AccessibleLabel||node.name);
    root.setAttribute('aria-required',String(!!p.Required));
    root.setAttribute('aria-invalid',String(!!p.Required&&!node.selection?.length));
    root.style.flexDirection=p.Layout==='Horizontal'||stacked?'row':'column';
    root.style.gap=p.Layout==='Horizontal'||stacked?'12px':'0';
    root._groupName??='emu-radio-'+(++modernControlId);
    const children=(node.options||[]).map(o=>{
      let label=[...root.children].find(e=>e.dataset.index===String(o.index));
      if(!label){label=element('label',{'data-index':o.index});label.append(element('input',{type:'radio',name:root._groupName}),element('span'));}
      const input=label.querySelector('input');
      input.value=String(o.index);input.checked=(node.selection||[]).includes(o.index);
      input.disabled=disabled||!!o.disabled;
      input.setAttribute('aria-label',o.label);
      if(nativeRadio)input.tabIndex=Number(p.TabIndex??0);
      input.style.accentColor=p.RadioSelectionFill||p.BasePaletteColor||'#0f6cbd';
      input.style.setProperty('--radio-selection-fill',input.style.accentColor);
      input.style.width=input.style.height=(p.RadioSize??16)+'px';
      label.style.minHeight=(classicRadio?Math.max(p.RadioSize??20,(p.Size||14)*(p.LineHeight??1.2)):p.LineHeight||32)+'px';
      label.style.flexDirection=stacked?'column':'row';
      label.style.maxWidth='100%';
      label.style.paddingBlock=stacked?'8px':'';
      label.style.justifyContent=({Left:'flex-start',Center:'center',Right:'flex-end'}[p.Align]||'flex-start');
      label.querySelector('span').textContent=o.label;
      label.onclick=e=>{if($('inspect-toggle').checked){e.preventDefault();return;}if(classicRadio&&e.target===input&&!root._model.disabled&&(root._model.node.selection||[]).includes(o.index))emit(root._model.node,'OnSelect');};
      input.onchange=()=>{if(input.checked&&!root._model.disabled)emit(root._model.node,'OnChange',{indices:[Number(input.value)],option_token:root._model.node.option_token});};
      return label;
    });
    reconcile(root,children);
    return root;
  }
  if(!root._button){
    const id='emu-dropdown-'+(++modernControlId);
    const button=element('button',{class:'fx-dropdown-button',type:'button',role:'combobox','aria-haspopup':'listbox','aria-expanded':'false','aria-controls':id});
    const popup=element('div',{class:'fx-dropdown-popup',id,role:'listbox'});
    root.append(button);root._button=button;root._popup=popup;root._active=-1;
    root._close=()=>{popup.remove();button.setAttribute('aria-expanded','false');button.removeAttribute('aria-activedescendant');if(activeDropdown===root)activeDropdown=null;};
    root._entries=()=>[...(root._model.node.family==='Classic/DropDown'&&!root._model.p.AllowEmptySelection?[]:[{index:null,label:root._model.p.InputTextPlaceholder||'Select…'}]),...(root._model.node.options||[])];
    root._draw=()=>{
      const entries=root._entries();
      root._active=Math.max(0,Math.min(entries.length-1,root._active));
      popup.replaceChildren(...entries.map((o,i)=>{
        const option=element('div',{role:'option',id:id+'-'+i,'aria-selected':String(o.index===null?!root._model.node.selection?.length:(root._model.node.selection||[]).includes(o.index)),'aria-disabled':String(!!o.disabled),class:i===root._active?'highlighted':''},o.label);
        option.onpointerdown=e=>e.preventDefault();
        option.onpointermove=()=>{if(root._active!==i){root._active=i;root._draw();}};
        option.onclick=()=>root._choose(i);
        if(root._model.node.family==='Classic/DropDown'){
          option.style.setProperty('--classic-selection-fill',root._model.p.SelectionFill||'transparent');option.style.setProperty('--classic-selection-color',root._model.p.SelectionColor||'inherit');
          option.classList.add('fx-classic-option');
        }
        return option;
      }));
      button.setAttribute('aria-activedescendant',id+'-'+root._active);
      popup.children[root._active]?.scrollIntoView({block:'nearest'});
    };
    root._open=()=>{
      if(root._model.disabled||$('inspect-toggle').checked)return;
      activeDropdown?._close();activeDropdown=root;
      root._active=Math.max(0,root._entries().findIndex(o=>o.index===(root._model.node.selection||[])[0]));
      const r=button.getBoundingClientRect();
      popup.style.width=Math.max(160,r.width)+'px';popup.style.left=Math.min(r.left,Math.max(0,window.innerWidth-Math.max(160,r.width)))+'px';
      const below=window.innerHeight-r.bottom-8;
      popup.style.top=below>=120?r.bottom+4+'px':'';popup.style.bottom=below>=120?'':window.innerHeight-r.top+4+'px';
      popup.style.maxHeight=Math.max(40,Math.min(root._model.node.family==='Classic/DropDown'?root._model.p.FlyoutMaximumHeight||400:280,below>=120?below:r.top-8))+'px';
      document.body.append(popup);button.setAttribute('aria-expanded','true');root._draw();
      if(root._model.node.family==='Classic/DropDown')emit(root._model.node,'OnSelect');
    };
    root._choose=i=>{const o=root._entries()[i];if(!o||o.disabled||root._model.disabled)return;root._close();button.focus();emit(root._model.node,'OnChange',{indices:o.index===null?[]:[o.index],option_token:root._model.node.option_token});};
    button.onclick=e=>{if($('inspect-toggle').checked)return;e.stopPropagation();button.getAttribute('aria-expanded')==='true'?root._close():root._open();};
    button.onkeydown=e=>{
      if($('inspect-toggle').checked||root._model.disabled)return;
      const open=button.getAttribute('aria-expanded')==='true',entries=root._entries();
      if(['Enter',' '].includes(e.key)){e.preventDefault();open?root._choose(root._active):root._open();return;}
      if(e.key==='Escape'){e.preventDefault();root._close();return;}
      if(e.key==='Tab'){root._close();return;}
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){
        e.preventDefault();if(!open)root._open();if(root._model.disabled)return;
        if(e.key==='Home')root._active=0;
        else if(e.key==='End')root._active=entries.length-1;
        else{const step=e.key==='ArrowDown'?1:-1;let i=root._active;do{i=Math.max(0,Math.min(entries.length-1,i+step));}while(entries[i]?.disabled&&i>0&&i<entries.length-1);root._active=i;}
        root._draw();return;
      }
      if(e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
        e.preventDefault();root._search=(Date.now()-(root._searchTime||0)<800?root._search||'':'')+e.key.toLowerCase();root._searchTime=Date.now();
        if(!open)root._open();if(root._model.disabled)return;
        const found=entries.findIndex(o=>!o.disabled&&o.label.toLowerCase().startsWith(root._search));
        if(found>=0){root._active=found;root._draw();}
      }
    };
    wrapper._cleanup=root._close;
  }
  const button=root._button,selected=(node.options||[]).find(o=>(node.selection||[]).includes(o.index));
  button.textContent=(selected?.label??p.InputTextPlaceholder??'Select…')+(p.Required?' *':'')+' ▾';
  button.disabled=mode==='Disabled'||mode==='Hidden';button.setAttribute('aria-readonly',String(mode==='View'));button.setAttribute('aria-label',p.AccessibleLabel||node.name);
  button.setAttribute('aria-required',String(!!p.Required));button.setAttribute('aria-invalid',String(p.ValidationState==='Error'));
  button.dataset.appearance=p.Appearance||'FilledDarker';
  if(classic){
    button.replaceChildren(element('span',{class:'fx-classic-selection'},selected?.label??''),element('span',{class:'fx-classic-chevron','aria-hidden':'true'},'▾'));
    applyClassicPresentation(button,wrapper,node,mode);
    const chevron=button.querySelector('.fx-classic-chevron');chevron.style.width=(p.ChevronWidth||34)+'px';
    for(const [key,value] of Object.entries({fill:p.ChevronFill,background:p.ChevronBackground,'hover-fill':p.ChevronHoverFill,'hover-background':p.ChevronHoverBackground,'disabled-fill':p.ChevronDisabledFill,'disabled-background':p.ChevronDisabledBackground}))chevron.style.setProperty('--classic-chevron-'+key,value||'transparent');
  }
  if(disabled||p.Visible===false)root._close();
  else if(activeDropdown===root)root._draw();
  return root;
}
document.addEventListener('pointerdown',e=>{if(activeDropdown&&!activeDropdown.contains(e.target)&&!activeDropdown._popup.contains(e.target))activeDropdown._close();});
window.addEventListener('resize',()=>activeDropdown?._close());
function renderModernIndicator(node,wrapper){
  const p=node.props||{},spinner=node.family==='ModernSpinner',cls=spinner?'fx-spinner':'fx-progress';
  let root=[...wrapper.children].find(e=>e.classList.contains(cls));if(!root)root=element('div',{class:cls});
  root.dataset.mode=p.DisplayMode||'Edit';root.setAttribute('aria-label',p.AccessibleLabel||p.Label||node.name);
  if(spinner){
    root.setAttribute('role','status');root.setAttribute('aria-live','polite');
    root.dataset.position=p.LabelPosition||'After';root.dataset.appearance=p.Appearance||'Primary';
    let ring=root.querySelector('.fx-spinner-ring');if(!ring){ring=element('span',{class:'fx-spinner-ring','aria-hidden':'true'});root.append(ring,element('span',{class:'fx-spinner-label'}));}
    ring.style.borderTopColor=p.Appearance==='Inverted'?'white':p.BasePaletteColor||'#0f6cbd';
    root.querySelector('.fx-spinner-label').textContent=p.Label||'';
  }else{
    const progress=node.progress||{indeterminate:true};root.setAttribute('role','progressbar');
    root.setAttribute('aria-valuemin','0');root.setAttribute('aria-busy',String(!!progress.indeterminate));
    if(progress.indeterminate){root.removeAttribute('aria-valuenow');root.removeAttribute('aria-valuemax');}
    else{root.setAttribute('aria-valuenow',String(progress.value));root.setAttribute('aria-valuemax',String(progress.max));}
    root.dataset.indeterminate=String(!!progress.indeterminate);root.dataset.shape=p.Shape||'Rounded';
    root.style.height=(p.Thickness==='Large'?8:4)+'px';
    let bar=root.firstChild;if(!bar){bar=element('div',{'aria-hidden':'true'});root.append(bar);}
    bar.style.width=progress.indeterminate?'35%':(100*progress.value/progress.max)+'%';
    bar.style.background={Success:'#107c10',Warning:'#bc4b09',Error:'#c50f1f'}[p.ProgressColor]||p.BasePaletteColor||'#0f6cbd';
  }
  return root;
}

function renderModernCombobox(node,wrapper,mode){
  const disabled=mode!=='Edit';
  const p=node.props||{};
  let root=[...wrapper.children].find(e=>e.classList.contains('fx-combobox'));
  if(!root){
    root=element('div',{class:'fx-combobox'});
    const id='emu-combo-'+(++modernControlId);
    const input=element('input',{class:'fx-combobox-input',type:'text',role:'combobox',autocomplete:'off','aria-autocomplete':'list','aria-haspopup':'listbox','aria-expanded':'false','aria-controls':id});
    const clear=element('button',{class:'fx-combobox-clear',type:'button','aria-label':'Clear selection'},'×');
    const arrow=element('button',{class:'fx-combobox-arrow',type:'button',tabindex:'-1','aria-label':'Open choices'},'▾');
    const popup=element('div',{class:'fx-dropdown-popup fx-combobox-popup',id,role:'listbox'});
    root.append(input,clear,arrow);root._input=input;root._popup=popup;root._draft=node.search_text||'';root._reset=node.search_reset;root._active=0;
    root._summary=()=> (root._model.node.selected_labels||[]).join(root._model.p.MultiValueDelimiter??', ');
    root._close=()=>{popup.remove();input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');input.value=root._model?.node.family==='ComboBox'&&root._model.p.SelectMultiple?'':root._summary();if(activeDropdown===root)activeDropdown=null;};
    root._cancel=()=>{clearTimeout(root._timer);root._timer=null;};
    root._cleanup=()=>{root._cancel();root._close();};
    root._sendSearch=()=>{
      root._cancel();const query=root._draft,reset=root._reset;
      enqueue(async()=>{
        if(!root.isConnected||root._reset!==reset||root._draft!==query||root._model.disabled||!root._model.p.IsSearchable)return;
        state=await api('/api/event',{path:root._model.node.path,name:'OnSearch',value:{text:query,reset_token:reset}});renderState();
      });
    };
    root._draw=()=>{
      const m=root._model,waiting=root._draft!==(m.node.search_text||'');
      popup.setAttribute('aria-multiselectable',String(!!m.p.SelectMultiple));
      if(waiting||!m.node.options?.length){
        popup.replaceChildren(element('div',{class:'fx-combobox-empty',role:'status'},waiting?'Searching…':'No matches'));
        input.removeAttribute('aria-activedescendant');return;
      }
      root._active=Math.max(0,Math.min(m.node.options.length-1,root._active));
      popup.replaceChildren(...m.node.options.map((o,i)=>{
        const selected=(m.node.selection||[]).includes(o.index);
        const option=element('div',{role:'option',id:id+'-'+i,'aria-selected':String(selected),'aria-disabled':String(!!o.disabled),class:i===root._active?'highlighted':''});
        option.append(element('span',{class:'fx-combobox-check','aria-hidden':'true'},selected?'✓':''));
        if(m.node.family==='Classic/ComboBox'){
          const copy=element('span',{class:'fx-classic-combo-copy'});copy.append(element('span',{},o.label));
          if(o.secondary)copy.append(element('span',{class:'fx-classic-combo-secondary'},o.secondary));
          if(o.person)option.append(element('span',{class:'fx-classic-combo-person','aria-hidden':'true'},o.label.split(/\s+/).map(w=>w[0]||'').slice(0,2).join('')));
          option.append(copy);option.classList.add('fx-classic-option');
          option.style.setProperty('--classic-selection-fill',m.p.SelectionFill||'transparent');option.style.setProperty('--classic-selection-color',m.p.SelectionColor||'inherit');
          if(o.navigable){const nav=element('button',{type:'button','aria-label':'Navigate '+o.label},'↗');nav.onpointerdown=e=>e.preventDefault();nav.onclick=e=>{e.stopPropagation();emit(root._model.node,'OnNavigate',{index:o.index,option_token:root._model.node.option_token});};option.append(nav);}
        }else{const copy=element('span',{},o.label);if(m.node.family==='ComboBox'&&o.secondary)copy.append(element('span',{class:'fx-classic-combo-secondary'},o.secondary));option.append(copy);}
        option.onpointerdown=e=>e.preventDefault();option.onpointermove=()=>{if(root._active!==i){root._active=i;root._draw();}};
        option.onclick=()=>root._choose(i);return option;
      }));
      input.setAttribute('aria-activedescendant',id+'-'+root._active);popup.children[root._active]?.scrollIntoView({block:'nearest'});
    };
    root._open=()=>{
      const m=root._model;if(m.disabled||$('inspect-toggle').checked||activeDropdown===root)return;
      activeDropdown?._close();activeDropdown=root;
      root._active=Math.max(0,(m.node.options||[]).findIndex(o=>(m.node.selection||[]).includes(o.index)));
      const r=root.getBoundingClientRect(),width=Math.max(180,r.width),below=window.innerHeight-r.bottom-8;
      popup.style.width=width+'px';popup.style.left=Math.min(r.left,Math.max(0,window.innerWidth-width))+'px';
      popup.style.top=below>=120?r.bottom+4+'px':'';popup.style.bottom=below>=120?'':window.innerHeight-r.top+4+'px';
      popup.style.maxHeight=Math.max(80,Math.min(m.node.family==='Classic/ComboBox'?m.p.FlyoutMaximumHeight??400:280,below>=120?below:r.top-8))+'px';
      document.body.append(popup);input.setAttribute('aria-expanded','true');input.value=m.p.IsSearchable?root._draft:root._summary();root._draw();
      if(m.node.family==='Classic/ComboBox')emit(m.node,'OnSelect');
    };
    root._choose=i=>{
      const m=root._model,o=m.node.options?.[i];if(!o||o.disabled||root._draft!==(m.node.search_text||''))return;
      const value={operation:'toggle',index:o.index,option_token:m.node.option_token};
      if(!m.p.SelectMultiple)root._close();input.focus();emit(m.node,'OnChange',value);
    };
    input.onfocus=()=>root._open();input.onclick=e=>{if(!$('inspect-toggle').checked){e.stopPropagation();root._open();}};
    input.oninput=()=>{
      if(root._model.disabled||!root._model.p.IsSearchable||$('inspect-toggle').checked)return;
      root._draft=input.value;root._active=0;root._draw();root._cancel();
      if(root._model.node.family==='ComboBox'){const trigger=root._model.p.TriggerOutput||'Keypress';if(trigger==='Delayed')root._timer=setTimeout(root._sendSearch,500);else if(trigger==='Keypress')root._sendSearch();}
      else if(root._model.p.DelayOutput)root._timer=setTimeout(root._sendSearch,500);else root._sendSearch();
    };
    input.onkeydown=e=>{
      if($('inspect-toggle').checked||root._model.disabled)return;
      if(e.key==='Escape'){e.preventDefault();root._close();return;}
      if(e.key==='Tab'){root._close();return;}
      if(e.key==='Enter'&&e.altKey&&root._model.node.family==='Classic/ComboBox'){const o=(root._model.node.options||[])[root._active];if(o?.navigable){e.preventDefault();emit(root._model.node,'OnNavigate',{index:o.index,option_token:root._model.node.option_token});}return;}
      if(e.key==='Enter'){e.preventDefault();if(activeDropdown===root)root._choose(root._active);else root._open();return;}
      if(['ArrowDown','ArrowUp'].includes(e.key)||!root._model.p.IsSearchable&&['Home','End',' '].includes(e.key)){
        e.preventDefault();if(activeDropdown!==root){root._open();return;}
        const options=root._model.node.options||[];
        const step=e.key==='ArrowUp'||e.key==='End'?-1:1;
        let i=e.key==='Home'?0:e.key==='End'?options.length-1:Math.max(0,Math.min(options.length-1,root._active+step));
        while(options[i]?.disabled&&i+step>=0&&i+step<options.length)i+=step;
        root._active=i;root._draw();
      }else if(!root._model.p.IsSearchable&&e.key.length===1&&!e.ctrlKey&&!e.metaKey&&!e.altKey){
        e.preventDefault();root._typeahead=(Date.now()-(root._typeaheadTime||0)<800?root._typeahead||'':'')+e.key.toLowerCase();root._typeaheadTime=Date.now();
        root._open();const i=(root._model.node.options||[]).findIndex(o=>!o.disabled&&o.label.toLowerCase().startsWith(root._typeahead));
        if(i>=0){root._active=i;root._draw();}
      }
    };
    clear.onpointerdown=arrow.onpointerdown=e=>e.preventDefault();
    clear.onclick=e=>{e.stopPropagation();const m=root._model;root._close();emit(m.node,'OnChange',{operation:'clear',option_token:m.node.option_token});};
    arrow.onclick=e=>{e.stopPropagation();activeDropdown===root?root._close():root._open();input.focus({preventScroll:true});};
    root.addEventListener('focusout',e=>{if(!root.contains(e.relatedTarget)){if(root._model.node.family==='ComboBox'&&root._model.p.TriggerOutput==='FocusOut'&&root._draft!==(root._model.node.search_text||''))root._sendSearch();root._close();}});
    wrapper._cleanup=root._cleanup;
  }
  const oldQuery=root._model?.node.search_text||'';
  root._model={node,p,disabled,mode};root.dataset.mode=mode;root.dataset.appearance=p.Appearance||'FilledDarker';
  if(root._reset!==node.search_reset){root._cancel();root._reset=node.search_reset;root._draft=node.search_text||'';root._close();}
  else if(root._draft===oldQuery)root._draft=node.search_text||'';
  const input=root._input;input.disabled=mode==='Disabled'||mode==='Hidden';input.readOnly=disabled||!p.IsSearchable;
  input.setAttribute('aria-readonly',String(mode==='View'));
  input.setAttribute('aria-label',p.AccessibleLabel||node.name);input.setAttribute('aria-required',String(!!p.Required));input.setAttribute('aria-invalid',String(p.ValidationState==='Error'||!!p.Required&&!node.selected_labels?.length));
  input.setAttribute('aria-autocomplete',p.IsSearchable?'list':'none');input.placeholder=node.family==='Classic/ComboBox'&&!p.IsSearchable?'':p.InputTextPlaceholder??'Find items';
  if(node.family==='Classic/ComboBox'){
    applyClassicPresentation(root,wrapper,node,mode);root.classList.add('fx-classic-combobox');
    let tags=root.querySelector('.fx-classic-combo-tags');if(!tags){tags=element('div',{class:'fx-classic-combo-tags','aria-label':'Selected items'});root.prepend(tags);}
    const show=p.SelectMultiple&&!!node.selected_labels?.length;
    tags.hidden=!show;input.classList.toggle('fx-classic-combo-tag-input',show);
    tags.style.setProperty('--tag-fill',p.SelectionTagFill||'transparent');tags.style.setProperty('--tag-color',p.SelectionTagColor||'inherit');
    tags.replaceChildren(...(show?node.selected_labels:[]).map((label,index)=>{
      const tag=element('span',{class:'fx-classic-combo-tag'},label);
      if(mode==='Edit'){const remove=element('button',{type:'button','aria-label':'Remove '+label},'×');remove.onpointerdown=e=>e.preventDefault();remove.onclick=e=>{e.stopPropagation();input.focus({preventScroll:true});emit(root._model.node,'OnChange',{operation:'remove',index,option_token:root._model.node.option_token});};tag.append(remove);}
      return tag;
    }));
    const chevron=root.querySelector('.fx-combobox-arrow');chevron.classList.add('fx-classic-chevron');chevron.style.width=(p.ChevronWidth??34)+'px';
    for(const [key,value] of Object.entries({fill:p.ChevronFill,background:p.ChevronBackground,'hover-fill':p.ChevronHoverFill,'hover-background':p.ChevronHoverBackground,'disabled-fill':p.ChevronDisabledFill,'disabled-background':p.ChevronDisabledBackground}))chevron.style.setProperty('--classic-chevron-'+key,value||'transparent');
    popupBorder(root._popup,p);
  }
  if(node.family==='ComboBox'){
    applyCanvasInputStyle(input,wrapper,p);applyCanvasSelectorStyle(root,wrapper,p);popupBorder(root._popup,p);
    let tags=root.querySelector('.fx-canvas-combo-tags');if(!tags){tags=element('div',{class:'fx-classic-combo-tags fx-canvas-combo-tags','aria-label':'Selected items'});root.prepend(tags);}
    tags.hidden=!p.SelectMultiple||!node.selected_labels?.length;
    tags.replaceChildren(...(tags.hidden?[]:node.selected_labels).map((label,index)=>{const tag=element('span',{class:'fx-classic-combo-tag'},label);if(mode==='Edit'){const remove=element('button',{type:'button','aria-label':'Remove '+label},'×');remove.onpointerdown=e=>e.preventDefault();remove.onclick=e=>{e.stopPropagation();emit(root._model.node,'OnChange',{operation:'remove',index,option_token:root._model.node.option_token});};tag.append(remove);}return tag;}));
  }
  root.querySelector('.fx-combobox-clear').hidden=mode==='View'||!node.selected_labels?.length;
  root.querySelector('.fx-combobox-clear').disabled=disabled;root.querySelector('.fx-combobox-arrow').disabled=disabled;
  if(disabled||p.Visible===false){root._cancel();root._close();}
  else if(activeDropdown===root){const value=p.IsSearchable?root._draft:root._summary();if(input.value!==value)input.value=value;root._draw();}
  else{const value=['Classic/ComboBox','ComboBox'].includes(node.family)&&p.SelectMultiple&&node.selected_labels?.length?'':root._summary()||p.NoSelectionText||'';if(input.value!==value)input.value=value;}
  return root;
}

function popupBorder(popup,p){popup.style.borderColor=p.BorderColor||"#d1d1d1";popup.style.borderStyle=(p.BorderStyle||"Solid").toLowerCase();popup.style.borderWidth=(p.BorderThickness??1)+"px";}
