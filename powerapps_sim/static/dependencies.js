'use strict';
let dependencyReport=null,dependencyQuery='',dependencyOffset=0,dependencyRequest=0;
async function loadDependencies(){
  const request=++dependencyRequest;
  const report=await api('/api/dependencies?query='+encodeURIComponent(dependencyQuery)+'&offset='+dependencyOffset+'&limit=50');
  if(request===dependencyRequest)dependencyReport=report;
}
function dependencyName(key){
  if(!Array.isArray(key))return '—';
  const [kind,path,name,row]=key;
  if(kind==='field')return key[3]+'.'+key[4].join('.')+' · '+path;
  if(kind==='query-result')return dependencyName(path)+' result';
  if(kind==='function-result')return name+'(…) · '+path;
  if(kind==='query')return name+'(…) · '+path+' ['+row.join('–')+']';
  if(kind==='query-row')return name+' · '+path+' · '+JSON.stringify(key[4]);
  if(kind==='query-field'||kind==='query-record'||kind==='query-disambiguation')return dependencyName(path[1])+' · '+JSON.stringify(path[2])+(name?' · '+name:'');
  if(kind==='query-row-present')return dependencyName(path)+' · exists '+JSON.stringify(name);
  if(kind==='named')return 'App.Formulas.'+path;
  if(kind==='app')return 'App.'+path;
  if(kind==='identifier')return (key[4]||row||'App')+'.'+path;
  if(kind==='parameter')return 'Param('+JSON.stringify(path)+')';
  if(kind==='environment'||kind==='list')return path;
  if(kind==='row-input'||kind==='row-present')return (kind==='row-input'?'Row value: ':'Row exists: ')+path+' · '+String(name).slice(0,12);
  return path+(name?'.'+name:'');
}
function renderDependencies(out){
  if(!dependencyReport||out.dataset.mode!=='dependencies')return;
  let toolbar=out.querySelector('.dependency-toolbar');
  if(!toolbar){
    toolbar=element('div',{class:'dependency-toolbar'});
    const filter=element('input',{type:'search','aria-label':'Filter dependencies',placeholder:'Find a control or formula'});filter.value=dependencyQuery;
    let debounce;
    filter.oninput=()=>{dependencyQuery=filter.value;dependencyOffset=0;clearTimeout(debounce);debounce=setTimeout(()=>action(async()=>{await loadDependencies();renderDependencies(out);})(),150);};
    toolbar.append(filter);out.append(toolbar,element('div',{class:'table-scroll dependency-table-scroll',tabindex:0,'aria-label':'Dependencies table'}));
  }
  const report=dependencyReport,scroller=out.querySelector('.dependency-table-scroll');
  const left=scroller.scrollLeft,top=scroller.scrollTop,focus=out.contains(document.activeElement)?document.activeElement.dataset.liveFocus:null;
  toolbar.querySelector('.pagination')?.remove();
  const pager=element('div',{class:'pagination'});
  for(const [label,delta] of [['Previous',-50],['Next',50]]){
    const button=element('button',{'aria-label':label+' dependency rules'},label);
    button.disabled=delta<0?report.offset===0:report.next_offset===null;
    button.onclick=action(async()=>{dependencyOffset=Math.max(0,report.offset+delta);await loadDependencies();renderDependencies(out);});pager.append(button);
  }
  pager.append(element('span',{},report.total?`${report.offset+1}–${Math.min(report.offset+report.rows.length,report.total)} of ${report.total}`:'0 rules'));toolbar.append(pager);
  const table=element('table',{class:'value-table dependency-table'}),thead=element('thead'),head=element('tr');
  for(const text of ['Rule','Scope','Current value','Evaluations','Reuses','Last change','Observed inputs'])head.append(element('th',{scope:'col'},text));
  thead.append(head);table.append(thead);const tbody=element('tbody');
  for(const rule of report.rows){
    const key='dependency/'+JSON.stringify(rule.key),row=element('tr',{'data-dependency-rule':JSON.stringify(rule.key)});
    const name=element('td'),title=element('strong',{},rule.name);name.append(title,element('span',{class:'dependency-kind'},rule.kind));
    if(rule.formula!==null){
      const details=element('details',{class:'value-details'});details.dataset.liveKey=key+'/formula';
      details.append(element('summary',{'data-live-focus':key+'/formula'},'Formula'),element('pre',{},rule.formula));
      details.open=liveExpanded.has(details.dataset.liveKey);details.ontoggle=()=>{if(details.open)liveExpanded.add(details.dataset.liveKey);else liveExpanded.delete(details.dataset.liveKey);};name.append(details);
    }
    const scope=element('td',{},rule.path);if(rule.row_key)scope.append(element('code',{class:'dependency-row',title:rule.row_key},rule.row_key.slice(0,12)));
    const reason=element('td',{},rule.reason);if(rule.changed_input)reason.append(element('code',{},dependencyName(rule.changed_input)));
    const inputs=element('td');for(const dependency of rule.dependencies)inputs.append(element('code',{class:'dependency-edge'},dependencyName(dependency)));
    row.append(name,scope,valueCell(rule.value,null,key+'/value'),element('td',{},String(rule.evaluations)),element('td',{},String(rule.reuses)),reason,inputs);tbody.append(row);
  }
  table.append(tbody);scroller.replaceChildren(table);scroller.scrollLeft=left;scroller.scrollTop=top;
  if(focus)out.querySelector('[data-live-focus="'+CSS.escape(focus)+'"]')?.focus({preventScroll:true});
}
