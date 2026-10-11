'use strict';
// Python validates/commits values and builds calendar cells. The browser keeps drafts.
let activeCalendar=null;
function clearScalarError(root){if(root._reportedError&&$('status').textContent===root._reportedError)status('Ready');root._reportedError='';root._error='';}
function scalarSend(root,name,value){
  const token=root._token,path=root._model.node.path,revision=root._draftRevision;
  enqueue(async()=>{
    if(!root.isConnected||root._token!==token||root._model.mode!=='Edit')return;
    if(value.operation==='step'&&root._draftRevision===revision)value={...value,text:root._draft};
    try{
      state=await api('/api/event',{path,name,value:{...value,reset_token:token}});
      clearScalarError(root);root._accepted=value.text??(value.source==='typed'?value.value:undefined);renderState();if(selectedPath)await inspect(selectedPath);
    }catch(error){root._error=error.message;root._reportedError=error.message;root._input.setAttribute('aria-invalid','true');root._message.textContent=error.message;root._message.hidden=false;throw error;}
  });
}
function scalarRoot(wrapper,cls){
  let root=[...wrapper.children].find(e=>e.classList.contains(cls));
  if(root)return root;
  root=element('div',{class:'fx-scalar '+cls});root._input=element('input',{class:'fx-input',type:'text'});
  root._message=element('span',{class:'fx-input-error',role:'alert',hidden:''});root.append(root._input,root._message);root._draft='';root._server='';root._error='';return root;
}
function scalarModel(root,node,mode,server){
  root._model={node,p:node.props||{},mode};root.dataset.mode=mode;
  if(root._token!==node.input_reset){root._token=node.input_reset;root._draft=server;clearScalarError(root);root._close?.();}
  else if(root._draft===root._server||root._accepted===root._draft){root._draft=server;root._accepted=undefined;}
  root._server=server;if(mode!=='Edit'){root._draft=server;clearScalarError(root);root._close?.();}
  if(root._input.value!==root._draft)root._input.value=root._draft;
  root._input.disabled=mode==='Disabled'||mode==='Hidden';root._input.readOnly=mode==='View';
  root._input.setAttribute('aria-label',node.props.AccessibleLabel||node.name);
  root._input.setAttribute('aria-invalid',String(!!root._error||node.props.ValidationState==='Error'));
  root._message.textContent=root._error;root._message.hidden=!root._error;
  root.dataset.appearance=node.props.Appearance||'FilledDarker';
  root._input.style.textAlign={Left:'left',Center:'center',Right:'right'}[node.props.Align]||'left';
}
function renderModernNumberInput(node,wrapper,mode){
  const root=scalarRoot(wrapper,'fx-number'),input=root._input;
  if(!root._up){
    input.setAttribute('role','spinbutton');input.inputMode='decimal';
    const steps=element('span',{class:'fx-number-steps'});
    root._up=element('button',{type:'button',tabindex:'-1'},'▴');root._down=element('button',{type:'button',tabindex:'-1'},'▾');steps.append(root._up,root._down);root.insertBefore(steps,root._message);
    root._commit=()=>{if(root._model.mode!=='Edit'||$('inspect-toggle').checked)return;if(root._draft!==root._server)scalarSend(root,'OnChange',{text:root._draft,operation:'commit'});else if(root._reportedError){clearScalarError(root);renderState();}};
    root._step=direction=>{if(root._model.mode==='Edit'&&!$('inspect-toggle').checked){scalarSend(root,'OnChange',{text:root._draft,operation:'step',direction});input.focus({preventScroll:true});}};
    input.oninput=()=>{root._draftRevision=(root._draftRevision||0)+1;root._draft=input.value;root._error='';root._message.hidden=true;};input.onblur=root._commit;
    input.onkeydown=e=>{if(root._model.mode!=='Edit'||$('inspect-toggle').checked)return;if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();root._step(e.key==='ArrowUp'?1:-1);}else if(e.key==='Enter'){e.preventDefault();input.blur();}};
    root._up.onpointerdown=root._down.onpointerdown=e=>e.preventDefault();root._up.onclick=e=>{e.stopPropagation();root._step(1);};root._down.onclick=e=>{e.stopPropagation();root._step(-1);};
    input.onclick=e=>{if(!$('inspect-toggle').checked)e.stopPropagation();};
  }
  scalarModel(root,node,mode,node.formatted_value??String(node.value??''));
  input.placeholder=node.props.HintText||'';input.setAttribute('aria-valuetext',node.formatted_value??'');
  for(const [name,property] of [['aria-valuemin','Min'],['aria-valuemax','Max'],['aria-valuenow',null]]){const value=property?node.props[property]:node.value;if(value==null)input.removeAttribute(name);else input.setAttribute(name,String(value));}
  root._up.disabled=root._down.disabled=mode!=='Edit';root._up.setAttribute('aria-label','Increase '+(node.props.AccessibleLabel||node.name));root._down.setAttribute('aria-label','Decrease '+(node.props.AccessibleLabel||node.name));
  root._up.hidden=root._down.hidden=mode==='View';return root;
}
function renderModernDatePicker(node,wrapper,mode){
  const root=scalarRoot(wrapper,'fx-date'),input=root._input;
  if(!root._icon){
    const id='emu-calendar-'+(++modernControlId);input.setAttribute('aria-haspopup','dialog');input.setAttribute('aria-controls',id);input.setAttribute('aria-expanded','false');
    root._popup=element('div',{id,class:'fx-calendar',role:'dialog','aria-label':'Choose date'});
    root._icon=element('button',{type:'button',class:'fx-calendar-open','aria-label':'Open calendar'},'▦');root._clear=element('button',{type:'button',class:'fx-date-clear','aria-label':'Clear date'},'×');root.insertBefore(root._clear,root._message);root.insertBefore(root._icon,root._message);
    root._popup.onkeydown=e=>{if(['PageUp','PageDown'].includes(e.key)){e.preventDefault();const c=root._model.node.calendar,[year,month]=c.month.split('-').map(Number),offset=(e.key==='PageUp'?-1:1)*(e.shiftKey?12:1),index=year*12+month-1+offset,next=String(Math.floor(index/12)).padStart(4,'0')+'-'+String(index%12+1).padStart(2,'0');if(next>=c.start.slice(0,7)&&next<=c.end.slice(0,7))scalarSend(root,'OnCalendar',{month:next});return;}if(e.key==='Escape'){e.preventDefault();root._close();input.focus();}};
    root._close=()=>{root._popup.remove();input.setAttribute('aria-expanded','false');if(activeCalendar===root)activeCalendar=null;root._pendingDate=undefined;};
    root._choose=(value,source='calendar')=>{if(root._model.node.family==='Classic/DatePicker'&&source==='calendar'){root._pendingDate=value;root._draw();return;}root._draft=root._server;root._close();scalarSend(root,'OnChange',{value,source});input.focus({preventScroll:true});};
    root._draw=()=>{
      const c=root._model.node.calendar;if(!c)return;
      const focusedElement=root._popup.querySelector(':focus'),focused=focusedElement?.dataset.date,focusedLabel=focusedElement?.getAttribute('aria-label');
      const header=element('div',{class:'fx-calendar-header'}),prev=element('button',{type:'button','aria-label':'Previous month'},'‹'),next=element('button',{type:'button','aria-label':'Next month'},'›');
      prev.disabled=!c.previous;next.disabled=!c.next;prev.onclick=()=>scalarSend(root,'OnCalendar',{month:c.previous});next.onclick=()=>scalarSend(root,'OnCalendar',{month:c.next});
      const month=element('input',{type:'month','aria-label':'Calendar month',value:c.month,min:c.start.slice(0,7),max:c.end.slice(0,7)});month.onchange=()=>scalarSend(root,'OnCalendar',{month:month.value});header.append(prev,element('strong',{},c.title),next,month);
      const grid=element('div',{class:'fx-calendar-grid',role:'grid','aria-label':c.title});
      const headings=element('div',{class:'fx-calendar-row',role:'row'});for(const day of c.weekdays)headings.append(element('span',{role:'columnheader'},day));grid.append(headings);
      for(let row=0;row<6;row++){const line=element('div',{class:'fx-calendar-row',role:'row'});for(const day of c.days.slice(row*7,row*7+7)){
        const cell=element('button',{type:'button',role:'gridcell','data-date':day.date||'','aria-label':day.label||'Unavailable date','aria-selected':String(root._pendingDate===undefined?!!day.selected:day.date===root._pendingDate),class:day.outside?'outside':''},String(day.day));cell.disabled=!!day.disabled;cell.onclick=()=>root._choose(day.date);
        cell.onkeydown=e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','End'].includes(e.key)){e.preventDefault();const all=[...grid.querySelectorAll('[data-date]')],i=all.indexOf(cell);let j=e.key==='Home'?row*7:e.key==='End'?row*7+6:i+{ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7}[e.key];const direction=e.key==='Home'?1:e.key==='End'?-1:j>i?1:-1;while(all[j]?.disabled)j+=direction;all[j]?.focus();}else if(e.key==='Escape'){e.preventDefault();root._close();input.focus();}};
        line.append(cell);
      }grid.append(line);}
      const children=[header,grid];
      if(root._model.node.family==='Classic/DatePicker'){
        const footer=element('div',{class:'fx-calendar-footer'}),ok=element('button',{type:'button'},'OK'),cancel=element('button',{type:'button'},'Cancel');
        ok.onclick=()=>{const chosen=root._pendingDate;root._close();if(chosen!==undefined){root._draft=root._server;scalarSend(root,'OnChange',{value:chosen,source:'calendar'});}input.focus({preventScroll:true});};cancel.onclick=()=>{root._close();input.focus({preventScroll:true});};footer.append(ok,cancel);children.push(footer);
      }
      root._popup.replaceChildren(...children);if(focused)root._popup.querySelector('[data-date="'+focused+'"]')?.focus({preventScroll:true});else if(['Next month','Previous month','Calendar month'].includes(focusedLabel)){const target=root._popup.querySelector('[aria-label="'+focusedLabel+'"]');(target?.disabled?root._popup.querySelector('[aria-label="Calendar month"]'):target)?.focus({preventScroll:true});}
    };
    root._open=()=>{if(root._model.mode!=='Edit'||$('inspect-toggle').checked)return;activeCalendar?._close();activeDropdown?._close();activeCalendar=root;root._draw();const r=root.getBoundingClientRect(),below=innerHeight-r.bottom;root._popup.style.left=Math.min(r.left,Math.max(0,innerWidth-320))+'px';root._popup.style.top=below>335?r.bottom+4+'px':'';root._popup.style.bottom=below>335?'':innerHeight-r.top+4+'px';document.body.append(root._popup);input.setAttribute('aria-expanded','true');};
    input.oninput=()=>{root._draft=input.value;};input.onblur=()=>{if(root._model.mode==='Edit'&&root._model.p.IsEditable&&!$('inspect-toggle').checked&&root._draft!==root._server)scalarSend(root,'OnChange',{value:root._draft,source:'typed'});};
    input.onclick=e=>{if(!$('inspect-toggle').checked){e.stopPropagation();if(!root._model.p.IsEditable)root._open();}};
    input.onkeydown=e=>{if(e.key==='Escape'){root._close();return;}if(e.key==='ArrowDown'&&root._model.mode==='Edit'){e.preventDefault();root._open();(root._popup.querySelector('[aria-selected=true]:not(:disabled)')||root._popup.querySelector('[data-date]:not(:disabled)'))?.focus();}};
    root._icon.onpointerdown=root._clear.onpointerdown=e=>e.preventDefault();root._icon.onclick=e=>{e.stopPropagation();activeCalendar===root?root._close():root._open();};root._clear.onclick=e=>{e.stopPropagation();root._choose(null,'clear');};wrapper._cleanup=root._close;
  }
  const server=node.calendar?.formatted??String(node.value??'');
  scalarModel(root,node,mode,server);input.readOnly=mode!=='Edit'||!node.props.IsEditable;input.placeholder=node.props.InputTextPlaceholder??node.props.Placeholder??'';
  root._icon.disabled=root._clear.disabled=mode!=='Edit';root._icon.setAttribute('aria-label','Open calendar '+(node.props.AccessibleLabel||node.name));root._clear.setAttribute('aria-label','Clear date '+(node.props.AccessibleLabel||node.name));root._clear.hidden=mode==='View'||node.value==null;
  if(node.family==='Classic/DatePicker'){applyClassicPresentation(input,wrapper,node,mode);root.classList.add('fx-classic-date');root._icon.style.color=node.props.IconFill;root._icon.style.background=node.props.IconBackground;root._popup.style.setProperty('--calendar-selected',node.props.SelectedDateFill);root._popup.style.setProperty('--calendar-hover',node.props.HoverDateFill);root._popup.style.setProperty('--calendar-header',node.props.CalendarHeaderFill);root._popup.style.setProperty('--calendar-month',node.props.MonthColor);}
  if(node.family==='DatePicker'){applyCanvasSelectorStyle(input,wrapper,node.props);input.setAttribute('aria-required',String(!!node.props.Required));input.setAttribute('aria-invalid',String(!!root._error||node.props.ValidationState==='Error'||!!node.props.Required&&node.value==null));}
  if(activeCalendar===root)root._draw();return root;
}
document.addEventListener('pointerdown',e=>{if(activeCalendar&&!activeCalendar.contains(e.target)&&!activeCalendar._popup.contains(e.target))activeCalendar._close();});
window.addEventListener('resize',()=>activeCalendar?._close());

function settleScalarControls(){if(activeCalendar&&(!activeCalendar.isConnected||activeCalendar.closest('[hidden]')))activeCalendar._close();}

document.addEventListener('focusin',e=>{if(activeCalendar&&!activeCalendar.contains(e.target)&&!activeCalendar._popup.contains(e.target))activeCalendar._close();});
