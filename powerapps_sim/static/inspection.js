'use strict';
let liveQuery='',selectedCollection='',collectionPage=0;
const liveExpanded=new Set(),liveScroll=new Map(),liveTablePage=new Map();
const liveScopeSelection=new Map();
let liveScopeProject=null;

function valueText(value){
  if(value===null||value===undefined)return 'Blank';
  if(value?.$dynamic!==undefined)return value.$json??JSON.stringify(value.$dynamic);
  if(value?.$jsonNumber!==undefined)return value.$jsonNumber;
  if(value?.$decimal!==undefined)return value.$decimal;
  if(value?.$enum)return value.$enum.namespace+(value.$enum.member==='CalculatedOptionSetValue'?' · '+JSON.stringify(value.$enum.value):'.'+value.$enum.member);
  if(typeof value?.$control==='string')return value.$control;
  return typeof value==='object'?JSON.stringify(value):String(value);
}
function valueType(value,type){
  if(value===null||value===undefined)return 'Blank';
  if(value?.$error)return 'Error';
  if(value?.$dynamic!==undefined)return 'Dynamic';
  if(value?.$jsonNumber!==undefined)return 'Dynamic Number';
  if(value?.$decimal!==undefined)return type?.kind==='Currency'?'Currency':'Decimal';
  if(value?.$enum)return 'Enum · '+value.$enum.namespace;
  if(typeof value?.$control==='string')return type?.kind==='Screen'?'Screen':'Control';
  if(Array.isArray(value))return 'Table';
  if(typeof value==='object')return 'Record';
  if(type&& !['Unknown','Blank','Error','Void'].includes(type.kind))return type.kind;
  return {number:'Number',string:'Text',boolean:'Boolean'}[typeof value]||'Unknown';
}
function typeText(type){
  if(!type)return 'Unknown';
  if(type.declared)return type.kind+' ('+typeText(type.declared)+')';
  if(type.kind==='Enum')return (type.name||'Unknown')+' enum';
  if(type.kind==='Record')return '{'+Object.entries(type.fields||{}).map(([name,t])=>name+': '+typeText(t)).join(', ')+(type.open?' …':'')+'}';
  if(type.kind==='Table')return '['+typeText(type.row)+']';
  return type.kind;
}
function typeBadge(kind,type){
  const badge=element('span',{class:'value-type '+kind.toLowerCase().replaceAll(' ','-')},kind);
  badge.title=type?.declared?'Declared '+typeText(type.declared):typeText(type);
  if(type?.origin==='binding')badge.title+=' · inferred from source';
  return badge;
}
function controlReference(value,key){
  if(typeof value?.$control!=='string'||typeof value?.path!=='string')return null;
  const button=element('button',{class:'control-reference','aria-label':'Inspect '+value.$control},value.$control);
  if(key)button.dataset.liveFocus=key;
  button.title=value.path;button.onclick=action(()=>inspect(value.path));return button;
}
function valueContent(value,type,key,depth=0,label=key){
  const control=controlReference(value,key);if(control)return control;
  if(type?.kind==='Media'&&typeof value==='string'&&value.startsWith('/api/asset/')){
    const video=/\.(mp4|webm|mov|m4v)(?:\?|$)/i.test(value);
    const player=element(video?'video':'audio',{controls:true,preload:'none','aria-label':label||'Media'});
    player.src=value;player.style.maxWidth='320px';return player;
  }
  const kind=valueType(value,type),aggregate=['Record','Table','Error'].includes(kind)||kind==='Dynamic'&&typeof value.$dynamic==='object'&&value.$dynamic!==null;
  if(aggregate&&depth<12){
    const details=element('details',{class:'value-details'}),content=element('div',{class:'value-expanded'});
    const current=kind==='Dynamic'?value.$dynamic:kind==='Error'?value.$error:value;
    const isTable=Array.isArray(current),count=isTable?current.length:Object.keys(current||{}).length;
    const summary=element('summary',{'data-live-focus':key},(kind==='Error'?(current.Message||'Error'):kind)+(kind==='Error'?'':' · '+count+(isTable?' rows':' fields')));
    details.dataset.liveKey=key;
    let built=false;
    const build=()=>{
      if(built)return;built=true;
      if(isTable){
        const keys=[...new Set(current.flatMap(row=>row&&typeof row==='object'&&!row.$error?Object.keys(row):['Value']).concat(Object.keys(type?.row?.fields||{})))];
        const scroller=element('div',{class:'table-scroll',tabindex:0,'aria-label':'Table '+label,'data-live-scroll':key});
        content.append(scroller);
        let page=Math.min(liveTablePage.get(key)||0,Math.max(0,Math.ceil(current.length/50)-1)),previous,next,range;
        const draw=()=>{
          liveTablePage.set(key,page);
          scroller.replaceChildren(dataTable(current.slice(page*50,(page+1)*50).map(row=>row&&typeof row==='object'&&!row.$error?row:{Value:row}),keys,type?.row,key+'/'+page,depth+1));
          if(previous){previous.disabled=page===0;next.disabled=(page+1)*50>=current.length;range.textContent=`${page*50+1}–${Math.min((page+1)*50,current.length)} of ${current.length}`;}
        };
        if(current.length>50){
          const pager=element('div',{class:'pagination'});
          previous=element('button',{'aria-label':'Previous rows of '+label,'data-live-focus':key+'/Previous'},'Previous');
          next=element('button',{'aria-label':'Next rows of '+label,'data-live-focus':key+'/Next'},'Next');range=element('span',{class:'value-count'});
          previous.onclick=()=>{page--;draw();scroller.scrollTop=0;};next.onclick=()=>{page++;draw();scroller.scrollTop=0;};
          pager.append(previous,next,range);content.append(pager);
        }
        draw();
      }else{
        const table=element('table',{class:'record-values'});
        for(const [field,item] of Object.entries(current||{})){
          const tr=element('tr');tr.append(element('th',{scope:'row'},field),valueCell(item,type?.fields?.[field],key+'/'+field,depth+1,field));table.append(tr);
        }
        const scroller=element('div',{class:'table-scroll',tabindex:0,'aria-label':'Record '+label,'data-live-scroll':key});scroller.append(table);content.append(scroller);
      }
    };
    details.ontoggle=()=>{if(details.open){liveExpanded.add(key);build();}else liveExpanded.delete(key);};
    if(liveExpanded.has(key)){details.open=true;build();}
    details.append(summary,content);return details;
  }
  const wrap=element('span',{class:'scalar-value'});
  if(kind==='Color'&&typeof value==='string'&&CSS.supports('color',value)){
    const swatch=element('span',{class:'color-swatch','aria-hidden':'true'});swatch.style.backgroundColor=value;wrap.append(swatch);
  }
  if(kind==='Image'&&typeof value==='string'&&(/^(data:image\/|\/api\/asset\/)/i).test(value)){
    const preview=element('img',{class:'value-image',src:value,alt:'Preview of '+label});preview.onerror=()=>{preview.hidden=true;};wrap.append(preview);
  }
  const code=element('code',{},valueText(value));code.title=valueText(value);wrap.append(code);return wrap;
}
function valueCell(value,type,key='',depth=0,label=key){
  const td=element('td');td.append(typeBadge(valueType(value,type),type),valueContent(value,type,key,depth,label));return td;
}
function dataTable(rows,keys,type,key='table',depth=0){
  const table=element('table',{class:'value-table'}),cols=element('colgroup');
  let width=0;for(const name of keys){const size=['Record','Table','Dynamic','Error','Media'].includes(type?.fields?.[name]?.kind)?360:190,col=element('col');col.style.width=size+'px';cols.append(col);width+=size;}table.append(cols);table.style.minWidth=Math.max(190,width)+'px';
  const thead=element('thead'),head=element('tr');
  for(const name of keys){
    const th=element('th',{scope:'col'}),field=type?.fields?.[name];th.append(element('span',{},name));
    if(field){const declared=field.declared||field;th.append(typeBadge(declared.kind,declared));}
    head.append(th);
  }
  thead.append(head);table.append(thead);const body=element('tbody');
  rows.forEach((row,index)=>{const tr=element('tr');for(const name of keys)tr.append(valueCell(row?.[name],type?.fields?.[name],key+'/'+index+'/'+name,depth,name));body.append(tr);});
  table.append(body);return table;
}
function liveEntries(){
  const entries=[],types=state.types||{};
  const add=(values,schemas,scope,category,scopeKey=scope,scopeLabel=scope)=>{
    for(const name of new Set([...Object.keys(values||{}),...Object.keys(schemas||{})]))entries.push({name,value:values?.[name]??(category==='collections'?[]:null),type:schemas?.[name],scope,scopeKey,scopeLabel,key:JSON.stringify([scopeKey,category,name])});
  };
  if(inspectorMode==='globals'){
    add(state.globals,types.globals,'Global','variables',JSON.stringify(['app','globals']));
    for(const screen of new Set([...Object.keys(state.contexts||{}),...Object.keys(types.contexts||{})]))add(state.contexts?.[screen],types.contexts?.[screen],screen+' · screen','variables',JSON.stringify(['screen',screen]),screen+' · screen');
    for(const path of new Set([...Object.keys(state.components||{}),...Object.keys(types.components||{})]))add(state.components?.[path]?.variables,types.components?.[path]?.variables,path,'variables',JSON.stringify(['component',path]));
  }else if(inspectorMode==='components'){
    for(const [path,instance] of Object.entries(state.component_contracts||{}))for(const [name,contract] of Object.entries(instance.properties)){
      const callable=['Function','Action','Event'].includes(contract.kind);
      const signature=callable?name+'('+(contract.parameters||[]).map(p=>p.name+(p.optional?'?':'')+': '+typeText(p.type)+(Object.hasOwn(p,'default')?' = '+String(p.default).replace(/^=/,''):'' )).join(', ')+') → '+typeText(contract.type):null;
      entries.push({name,value:contract.error??(callable?signature:contract.value),type:contract.error?{kind:'Error'}:callable?{kind:contract.kind}:contract.type,scope:path+' · '+(contract.kind||'Contract'),scopeKey:JSON.stringify(['component',path]),scopeLabel:path,key:JSON.stringify([JSON.stringify(['component',path]),'properties',name]),path,contract});
    }
    for(const path of new Set([...Object.keys(state.components||{}),...Object.keys(types.components||{})]))for(const category of ['variables','collections']){
      add(state.components?.[path]?.[category],types.components?.[path]?.[category],path+' · '+category,category,JSON.stringify(['component',path]),path);
    }
  }else{
    add(state.collections,types.collections,'App','collections',JSON.stringify(['app','collections']));
    for(const path of new Set([...Object.keys(state.components||{}),...Object.keys(types.components||{})]))add(state.components?.[path]?.collections,types.components?.[path]?.collections,path,'collections',JSON.stringify(['component',path]));
  }
  return entries;
}
function liveScopeFilter(toolbar,entries){
  if(liveScopeProject!==project?.project_path){liveScopeProject=project?.project_path;liveScopeSelection.clear();}
  let select=toolbar.querySelector('select');
  if(!select){
    select=element('select',{'aria-label':'Runtime scope'});toolbar.append(select);
    select.onchange=()=>{liveScopeSelection.set(inspectorMode,select.value);collectionPage=0;renderLiveInspector($('inspector'));};
  }
  const scopes=[...new Map(entries.map(e=>[e.scopeKey,e.scopeLabel])).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
  const optionsSignature=JSON.stringify(scopes);
  if(select.dataset.options!==optionsSignature){
    // Tokens remain distinct even when an authored screen is named App/Global.
    select.replaceChildren(element('option',{value:''},'All scopes'),...scopes.map(([key,label])=>element('option',{value:key},label)));
    select.dataset.options=optionsSignature;
  }
  let selected=liveScopeSelection.get(inspectorMode)||'';
  if(selected&&!scopes.some(([key])=>key===selected)){selected='';liveScopeSelection.set(inspectorMode,'');}
  select.value=selected;
  return selected;
}
function renderLiveInspector(out){
  let toolbar=out.querySelector('.live-toolbar'),body=out.querySelector('.live-body');
  if(!toolbar){
    delete out._liveSignature;toolbar=element('div',{class:'live-toolbar'});
    const filter=element('input',{type:'search',placeholder:'Filter values','aria-label':'Filter runtime values'});filter.value=liveQuery;
    filter.oninput=()=>{liveQuery=filter.value;collectionPage=0;renderLiveInspector(out);};toolbar.append(filter);
    body=element('div',{class:'live-body'});out.replaceChildren(toolbar,body);
  }
  const entries=liveEntries(),scopeFilter=liveScopeFilter(toolbar,entries),signature=json({mode:inspectorMode,entries,liveQuery,scopeFilter,selectedCollection,collectionPage});
  if(out._liveSignature===signature)return;out._liveSignature=signature;
  const focus=body.contains(document.activeElement)?document.activeElement.closest('[data-live-focus]')?.dataset.liveFocus:null;
  const scrollTop=out.scrollTop;
  for(const scroller of body.querySelectorAll('[data-live-scroll]'))liveScroll.set(scroller.dataset.liveScroll,{x:scroller.scrollLeft,y:scroller.scrollTop});
  const filtered=entries.filter(e=>(!scopeFilter||e.scopeKey===scopeFilter)&&(e.name+' '+e.scope+' '+valueText(e.value)+' '+typeText(e.type)).toLowerCase().includes(liveQuery.toLowerCase()));
  body.replaceChildren();
  if(!filtered.length){body.className='live-body';body.append(element('p',{class:'empty-note'},entries.length?'No matching values.':'No values yet.'));return;}
  if(inspectorMode==='collections'){
    const list=element('div',{class:'collection-list','aria-label':'Collections','data-live-scroll':'collections/sidebar'}),content=element('div',{class:'collection-content'});
    if(!filtered.some(e=>e.key===selectedCollection))selectedCollection=filtered[0].key;
    for(const entry of filtered){
      const button=element('button',{class:entry.key===selectedCollection?'active':'','aria-pressed':String(entry.key===selectedCollection),'data-live-focus':entry.key},entry.name+' · '+(entry.value?.length||0));
      button.title=entry.scope;button.append(element('span',{class:'collection-scope'},entry.scope));
      button.onclick=()=>{selectedCollection=entry.key;collectionPage=0;renderLiveInspector(out);};list.append(button);
    }
    const entry=filtered.find(e=>e.key===selectedCollection),rows=Array.isArray(entry.value)?entry.value:[];
    const keys=[...new Set(rows.flatMap(r=>r&&typeof r==='object'&&!r.$error?Object.keys(r):['Value']).concat(Object.keys(entry.type?.row?.fields||{})))];
    collectionPage=Math.min(collectionPage,Math.max(0,Math.ceil(rows.length/50)-1));
    const pageRows=rows.slice(collectionPage*50,(collectionPage+1)*50).map(row=>row&&typeof row==='object'&&!row.$error?row:{Value:row});
    const scroller=element('div',{class:'table-scroll',tabindex:0,'aria-label':entry.name+' collection','data-live-scroll':entry.key,'data-live-focus':entry.key+'/scroll'});
    scroller.append(dataTable(pageRows,keys,entry.type?.row,entry.key+'/'+collectionPage));content.append(scroller);
    if(rows.length>50){
      const pager=element('div',{class:'pagination'});
      for(const [label,delta] of [['Previous',-1],['Next',1]]){
        const b=element('button',{'data-live-focus':entry.key+'/'+label},label);b.disabled=delta<0?collectionPage===0:(collectionPage+1)*50>=rows.length;
        b.onclick=()=>{collectionPage+=delta;renderLiveInspector(out);};pager.append(b);
      }
      pager.append(element('span',{},`${collectionPage*50+1}–${Math.min((collectionPage+1)*50,rows.length)} of ${rows.length}`));content.append(pager);
    }
    body.className='live-body collections-layout';body.append(list,content);
  }else{
    body.className='live-body';const table=element('table',{class:'runtime-values'}),thead=element('thead'),head=element('tr');
    for(const text of ['Name','Scope','Current value'])head.append(element('th',{scope:'col'},text));thead.append(head);table.append(thead);
    const tbody=element('tbody');for(const entry of filtered){const row=element('tr');row.dataset.liveValue=entry.name;row.dataset.liveScope=entry.scope;const name=element('td',{},entry.name),value=valueCell(entry.value,entry.type,entry.key,0,entry.name);if(entry.path){const button=element('button',{class:'control-reference','data-live-focus':entry.key+'/inspect','aria-label':'Inspect '+entry.path+' · '+entry.name},entry.name);button.onclick=action(()=>inspect(entry.path));name.replaceChildren(button);if(entry.contract.description)name.title=entry.contract.description;const formula=element('details',{class:'value-details'});formula.dataset.liveKey=entry.key+'/formula';const summary=element('summary',{'data-live-focus':entry.key+'/formula'},'Formula');formula.append(summary,element('pre',{},valueText(entry.contract.formula)));formula.open=liveExpanded.has(formula.dataset.liveKey);formula.ontoggle=()=>{if(formula.open)liveExpanded.add(formula.dataset.liveKey);else liveExpanded.delete(formula.dataset.liveKey);};value.append(formula);}row.append(name,element('td',{},entry.scope),value);tbody.append(row);}table.append(tbody);body.append(table);
  }
  if(focus)body.querySelector('[data-live-focus="'+CSS.escape(focus)+'"]')?.focus({preventScroll:true});
  for(const scroller of body.querySelectorAll('[data-live-scroll]')){const pos=liveScroll.get(scroller.dataset.liveScroll);if(pos){scroller.scrollLeft=pos.x;scroller.scrollTop=pos.y;}}
  out.scrollTop=scrollTop;
}
