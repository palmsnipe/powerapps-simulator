'use strict';
// Record editors retain JSON values; Python remains responsible for list validation.
function recordReadOnly(schema){return schema.readOnly===true||schema['x-ms-permission']==='read-only';}
function recordContainsReadOnly(schema){return recordReadOnly(schema)||Object.values(schema.properties||{}).some(recordContainsReadOnly)||(schema.items&&recordContainsReadOnly(schema.items));}
function recordPut(object,key,value){Object.defineProperty(object,key,{value,writable:true,enumerable:true,configurable:true});}
function recordCopy(value){return value===undefined?undefined:JSON.parse(JSON.stringify(value));}
function recordScalarEditor(name,schema,value){
  let input,convert;
  if(recordReadOnly(schema)){
    input=element('pre',{class:'record-readonly','aria-label':name,tabindex:0},value===undefined?'Blank':json(value));
    return {input,read:()=>value,focus:()=>input.focus(),rename:n=>input.setAttribute('aria-label',n)};
  }
  if(schema.type==='boolean'){
    input=element('select',{'aria-label':name});
    for(const [v,label] of [['','Blank'],['true','True'],['false','False']])input.append(element('option',{value:v},label));
    input.value=value==null?'':String(value);convert=()=>input.value===''?null:input.value==='true';
  }else if(schema.type==='number'&&schema.format==='decimal'){
    input=element('input',{type:'text',inputmode:'decimal','aria-label':name});input.value=value?.$decimal??value??'';
    convert=()=>{const v=input.value.trim();if(!v)return null;if(!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(v))throw Error(name+' expects a decimal');return {$decimal:v};};
  }else if(['number','integer'].includes(schema.type)){
    input=element('input',{type:'number',step:schema.type==='integer'?'1':'any','aria-label':name});input.value=value??'';
    convert=()=>{if(input.validity.badInput)throw Error(name+' expects a number');if(input.value==='')return null;const number=Number(input.value);if(!Number.isFinite(number))throw Error(name+' expects a finite number');return number;};
  }else if(schema.type==='string'){
    input=element(schema.maxLength>255?'textarea':'input',{'aria-label':name});input.value=value??'';
    if(schema.maxLength)input.maxLength=schema.maxLength;convert=()=>input.value;
  }else{
    input=element('textarea',{'aria-label':name+' JSON',spellcheck:false,class:'record-json'});input.value=value===undefined?'':json(value);
    convert=()=>input.value.trim()?JSON.parse(input.value):null;
  }
  let dirty=false;const initial=input.value;
  input.addEventListener('input',()=>{dirty=true;});input.addEventListener('change',()=>{dirty=true;});
  const read=()=>!dirty||input.value===initial?value:convert();
  return {input,read,focus:()=>input.focus(),rename:n=>{name=n;input.setAttribute('aria-label',schema.type?n:n+' JSON');}};
}
function recordFieldEditor(name,schema,value,depth=0){
  schema=schema||{};
  const object=value!==null&&typeof value==='object'&&!Array.isArray(value);
  const correctShape=value==null||schema.type==='array'&&Array.isArray(value)||schema.type==='object'&&object;
  const structured=depth<10&&!recordReadOnly(schema)&&correctShape&&(schema.type==='array'||schema.type==='object'&&Object.keys(schema.properties||{}).length);
  const scalarMatch=value==null||schema.type==='string'&&typeof value==='string'||schema.type==='boolean'&&typeof value==='boolean'||['number','integer'].includes(schema.type)&&(typeof value==='number'||schema.format==='decimal'&&object&&Object.keys(value).length===1&&typeof value.$decimal==='string');
  if(!structured)return recordScalarEditor(name,recordReadOnly(schema)||scalarMatch?schema:{},value);
  const root=element('div',{class:'record-complex','aria-label':name});
  const tools=element('div',{class:'record-complex-tools'}),toggle=element('button',{type:'button'},'JSON');
  const error=element('div',{class:'record-field-error',role:'alert',hidden:''}),body=element('div',{class:'record-complex-body'});
  tools.append(toggle);root.append(tools,error,body);
  let mode='fields',draft=value,editor=null,raw=null,rawInitial='';
  const fail=e=>{error.textContent=e.message;error.hidden=false;};
  function draw(){
    body.replaceChildren();error.hidden=true;
    if(mode==='json'){
      raw=element('textarea',{class:'record-json','aria-label':name+' JSON',spellcheck:false});raw.value=draft===undefined?'':json(draft);rawInitial=raw.value;
      if(recordContainsReadOnly(schema)){raw.readOnly=true;raw.title='Contains read-only fields';}
      body.append(raw);toggle.textContent=schema.type==='array'?'Rows':'Fields';
    }else{
      editor=schema.type==='array'?recordArrayEditor(name,schema,draft,depth):recordObjectEditor(name,schema,draft,depth);
      body.append(editor.input);toggle.textContent='JSON';
    }
    toggle.setAttribute('aria-label',(mode==='json'?'Edit ':'View ')+name+(mode==='json'?(schema.type==='array'?' rows':' fields'):' JSON'));
  }
  const read=()=>mode==='json'?(raw.value===rawInitial?draft:raw.value.trim()?JSON.parse(raw.value):null):editor.read();
  toggle.onclick=()=>{try{const next=read();if(mode==='json'&&next!=null&&(schema.type==='array'?!Array.isArray(next):typeof next!=='object'||Array.isArray(next)))throw Error(name+' expects '+(schema.type==='array'?'an array':'a record'));draft=next;mode=mode==='fields'?'json':'fields';draw();(mode==='json'?raw:editor.input.querySelector('input,select,textarea,button'))?.focus();}catch(e){fail(e);}};
  draw();
  return {input:root,read,focus:()=>{(mode==='json'?raw:editor.input.querySelector('input,select,textarea,button'))?.focus();},rename:n=>{name=n;root.setAttribute('aria-label',n);if(mode==='json')raw.setAttribute('aria-label',n+' JSON');else editor.rename(n);toggle.setAttribute('aria-label',(mode==='json'?'Edit ':'View ')+n+(mode==='json'?(schema.type==='array'?' rows':' fields'):' JSON'));}};
}
function recordObjectEditor(name,schema,value,depth){
  const root=element('div',{class:'record-object'}),tools=element('div',{class:'record-complex-tools'}),content=element('div',{class:'record-object-fields'});
  let current=value,fields=[];
  const create=element('button',{type:'button'},'Create record'),clear=element('button',{type:'button'},'Clear');tools.append(create,clear);root.append(tools,content);
  function draw(){
    content.replaceChildren();fields=[];create.hidden=current!=null;clear.disabled=current==null;
    create.setAttribute('aria-label','Create '+name+' record');clear.setAttribute('aria-label','Clear '+name);
    if(current==null){content.append(element('span',{class:'record-blank'},'Blank'));return;}
    const keys=[...new Set([...Object.keys(schema.properties||{}),...Object.keys(current)])];
    for(const key of keys){
      const child=schema.properties?.[key]||{},label=child.title||key,field=element('div',{class:'record-field'}),editor=recordFieldEditor(name+' '+label,child,current[key],depth+1);
      const required=(Array.isArray(schema.required)&&schema.required.includes(key))||child.required===true;
      field.append(element('span',{},label+(required?' *':'')),editor.input);fields.push({key,label,editor});content.append(field);
    }
  }
  function read(){if(current==null)return current;const result=recordCopy(current);for(const field of fields){const next=field.editor.read();if(next!==undefined)recordPut(result,field.key,next);}return result;}
  create.onclick=()=>{current=recordCopy(schema.default)??{};draw();fields[0]?.editor.focus();};clear.onclick=()=>{current=null;draw();create.focus();};draw();
  return {input:root,read,rename:n=>{name=n;create.setAttribute('aria-label','Create '+n+' record');clear.setAttribute('aria-label','Clear '+n);for(const f of fields)f.editor.rename(n+' '+f.label);}};
}
function recordArrayEditor(name,schema,value,depth){
  const root=element('div',{class:'record-array'}),tools=element('div',{class:'record-complex-tools'}),count=element('span',{class:'record-row-count'});
  const add=element('button',{type:'button'},'Add row'),empty=element('button',{type:'button'},'Empty'),clear=element('button',{type:'button'},'Clear');tools.append(count,add,empty,clear);
  const scroller=element('div',{class:'record-array-scroll',tabindex:0,'aria-label':name+' rows'}),table=element('table',{class:'record-array-grid'}),head=element('thead'),headRow=element('tr'),body=element('tbody');
  let current=value,rows=[];const item=schema.items||{},objectRows=item.type==='object'&&Object.keys(item.properties||{}).length;
  const keys=objectRows?[...new Set([...Object.keys(item.properties||{}),...(value||[]).flatMap(v=>v&&typeof v==='object'&&!Array.isArray(v)?Object.keys(v):[])])]:['Value'];
  headRow.append(element('th',{scope:'col',class:'record-row-action'},''));
  for(const key of keys){const child=objectRows?item.properties?.[key]||{}:item;const required=objectRows&&((Array.isArray(item.required)&&item.required.includes(key))||child.required===true);headRow.append(element('th',{scope:'col'},(objectRows?child.title||key:'Value')+(required?' *':'')));}
  head.append(headRow);table.append(head,body);table.style.minWidth=(keys.length*190+100)+'px';scroller.append(table);root.append(tools,scroller);
  function renumber(){
    count.textContent=current==null?'Blank':rows.length+(rows.length===1?' row':' rows');
    add.setAttribute('aria-label','Add '+name+' row');empty.setAttribute('aria-label','Empty '+name);clear.setAttribute('aria-label','Clear '+name);clear.disabled=current==null;
    rows.forEach((row,index)=>{row.remove.setAttribute('aria-label','Remove '+name+' row '+(index+1));for(const field of row.fields)field.editor.rename(name+' row '+(index+1)+(field.label?' '+field.label:''));});
  }
  function append(value){
    const tr=element('tr'),cell=element('td',{class:'record-row-action'}),remove=element('button',{type:'button'},'Remove');cell.append(remove);tr.append(cell);
    const row={value,tr,remove,fields:[],record:objectRows&&value!==null&&typeof value==='object'&&!Array.isArray(value)};rows.push(row);
    if(objectRows&&!row.record){
      const td=element('td',{colspan:keys.length}),editor=recordFieldEditor(name+' row '+rows.length,{},value,depth+1);td.append(editor.input);row.fields.push({key:null,label:'',editor});tr.append(td);
    }else for(const key of keys){
      const child=objectRows?item.properties?.[key]||{}:item,label=objectRows?child.title||key:'Value',td=element('td'),editor=recordFieldEditor(name+' row '+rows.length+' '+label,child,objectRows?value[key]:value,depth+1);
      td.append(editor.input);tr.append(td);row.fields.push({key,label,editor});
    }
    remove.onclick=()=>{const index=rows.indexOf(row);rows.splice(index,1);tr.remove();renumber();(rows[index]?.remove||rows[index-1]?.remove||add).focus();};body.append(tr);renumber();return row;
  }
  function read(){
    if(current==null)return current;
    return rows.map(row=>{if(!objectRows||!row.record)return row.fields[0].editor.read()??null;const result=recordCopy(row.value);for(const f of row.fields){const next=f.editor.read();if(next!==undefined)recordPut(result,f.key,next);}return result;});
  }
  add.onclick=()=>{if(current==null)current=[];const seed=item.default!==undefined?recordCopy(item.default):objectRows?{}:item.type==='string'?'':item.type==='boolean'?false:item.type==='number'||item.type==='integer'?0:null;const row=append(seed);row.fields[0]?.editor.focus();};
  empty.onclick=()=>{current=[];rows=[];body.replaceChildren();renumber();add.focus();};clear.onclick=()=>{current=null;rows=[];body.replaceChildren();renumber();add.focus();};
  for(const row of value||[])append(row);renumber();
  return {input:root,read,rename:n=>{name=n;scroller.setAttribute('aria-label',n+' rows');renumber();}};
}
