'use strict';
let modernGridId=0;
function renderModernGrid(node,wrapper,mode){
  let root=wrapper.querySelector(':scope > .fx-modern-grid');
  if(!root){
    root=element('div',{class:'fx-modern-grid'});root._id='emu-grid-'+(++modernGridId);root._widths=new Map();
    root._search=element('input',{type:'search',class:'fx-input',placeholder:'Search'});
    root._scroll=element('div',{class:'fx-grid-scroll'});root._table=element('table',{role:'grid',tabindex:'0'});
    root._cols=element('colgroup');root._head=element('thead');root._body=element('tbody');root._empty=element('div',{class:'fx-grid-empty'},'No records');
    root._table.append(root._cols,root._head,root._body);root._scroll.append(root._table,root._empty);root.append(root._search,root._scroll);
    root._send=(name,value)=>{const m=root._model;if(m.mode!=='Edit'||$('inspect-toggle').checked)return;emit(m.node,name,{...value,items_token:m.node.items_token});};
    root._search.oninput=()=>root._send('OnSearch',{query:root._search.value});
    root._scroll.onscroll=()=>{if(root._virtual)root._draw();};
    root._choose=(i,e)=>{const m=root._model,rows=m.node.rows||[];let ids=[i];const multi=m.node.props.SelectMultiple;
      if(multi&&e.shiftKey&&root._anchor!==undefined){const a=rows.findIndex(r=>r.index===root._anchor),b=rows.findIndex(r=>r.index===i);if(a>=0)ids=rows.slice(Math.min(a,b),Math.max(a,b)+1).filter(r=>!r.disabled).map(r=>r.index);}
      else root._anchor=i;
      root._send('OnChange',{indices:ids,toggle:!!(multi&&(e.ctrlKey||e.metaKey||e.type==='change'))});
    };
    root._table.onkeydown=e=>{if(e.target!==root._table||root._model.mode!=='Edit'||$('inspect-toggle').checked)return;const rows=root._model.node.rows||[];if(!rows.length)return;
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();let i=rows.findIndex(r=>r.index===root._model.node.latest);i=e.key==='Home'?0:e.key==='End'?rows.length-1:Math.max(0,Math.min(rows.length-1,i+(e.key==='ArrowDown'?1:-1)));
        const step=e.key==='ArrowUp'||e.key==='End'?-1:1;while(rows[i]?.disabled&&i+step>=0&&i+step<rows.length)i+=step;if(!rows[i]?.disabled){root._choose(rows[i].index,e);if(root._virtual){root._scroll.scrollTop=i*40;root._draw();}else root._body.children[i]?.scrollIntoView({block:'nearest',inline:'nearest'});}}
      if(root._model.node.props.SelectMultiple&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();root._send('OnChange',{indices:rows.filter(r=>!r.disabled).map(r=>r.index)});}
    };
  }
  root._model={node,mode};const p=node.props||{},columns=node.columns||[],rows=node.rows||[];root.dataset.mode=mode;
  if(root._epoch!==node.grid_epoch){root._epoch=node.grid_epoch;root._anchor=undefined;root._scroll.scrollTop=0;root._widths.clear();}
  root.style.setProperty('--grid-brand',p.BasePaletteColor||'#0f6cbd');root.style.fontSize=(p.Size??14)+'px';
  root._search.hidden=!p.Searchable;root._search.disabled=mode==='Disabled';root._search.readOnly=mode==='View';root._search.setAttribute('aria-label',(p.AccessibleLabel||node.name)+' search');
  if(document.activeElement!==root._search&&root._search.value!==node.search)root._search.value=node.search||'';
  root._table.setAttribute('aria-label',p.AccessibleLabel||node.name);root._table.setAttribute('aria-multiselectable',String(!!p.SelectMultiple));root._table.setAttribute('aria-readonly','true');root._table.setAttribute('aria-required',String(!!p.Required));root._table.setAttribute('aria-disabled',String(mode==='Disabled'));
  root._table.setAttribute('aria-rowcount',String(rows.length+1));root._table.setAttribute('aria-colcount',String(columns.length+(p.ShowSelector?1:0)));
  const live=new Set(columns.map(c=>c.path));for(const key of root._widths.keys())if(!live.has(key))root._widths.delete(key);
  const total=()=>columns.reduce((n,c)=>n+root._widths.get(c.path).width,p.ShowSelector?44:0);
  const cols=columns.map(c=>{const col=[...root._cols.children].find(e=>e.dataset.column===c.path)||element('col',{'data-column':c.path});let saved=root._widths.get(c.path);if(saved?.base!==c.width){saved={base:c.width,width:Math.max(48,c.width)};root._widths.set(c.path,saved);}col.style.width=saved.width+'px';return col;});
  reconcile(root._cols,p.ShowSelector?[element('col',{style:'width:44px'}),...cols]:cols);
  const heading=root._head.firstChild||element('tr');root._head.hidden=!p.ShowHeaders;
  const headings=columns.map(c=>{let th=[...heading.children].find(e=>e.dataset.column===c.path);if(!th){th=element('th',{'data-column':c.path,scope:'col'});th.append(element('button',{type:'button',class:'fx-grid-sort'}),element('span',{class:'fx-table-resize',role:'separator',tabindex:'0','aria-orientation':'vertical'}));}
    const button=th.firstChild;button.textContent=c.header;button.setAttribute('aria-label',c.header);button.disabled=!p.Sortable||mode!=='Edit';button.onclick=e=>{e.stopPropagation();root._send('OnSort',{column:c.path,descending:node.sort?.column===c.path?!node.sort.descending:false});};
    th.setAttribute('aria-sort',node.sort?.column===c.path?node.sort.descending?'descending':'ascending':'none');
    const handle=th.lastChild;handle.setAttribute('aria-label','Resize '+c.header);handle.setAttribute('aria-valuenow',String(root._widths.get(c.path).width));
    const resize=width=>{root._widths.get(c.path).width=Math.max(48,width);cols[columns.indexOf(c)].style.width=root._widths.get(c.path).width+'px';root._table.style.width=total()+'px';handle.setAttribute('aria-valuenow',String(root._widths.get(c.path).width));};
    handle.onkeydown=e=>{if(mode==='Disabled'||$('inspect-toggle').checked)return;if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();e.stopPropagation();resize(root._widths.get(c.path).width+(e.key==='ArrowRight'?20:-20));}};
    handle.onpointerdown=e=>{if(mode==='Disabled'||$('inspect-toggle').checked)return;e.preventDefault();e.stopPropagation();handle.setPointerCapture(e.pointerId);const start=e.clientX,width=root._widths.get(c.path).width,scale=wrapper.getBoundingClientRect().width/(wrapper.offsetWidth||1);handle.onpointermove=m=>resize(width+(m.clientX-start)/(scale||1));handle.onpointerup=()=>{handle.onpointermove=null;};handle.onlostpointercapture=()=>{handle.onpointermove=null;};};return th;
  });reconcile(heading,p.ShowSelector?[element('th',{scope:'col'},''),...headings]:headings);reconcile(root._head,[heading]);root._table.style.width=total()+'px';
  root._virtual=rows.length>2000;root._draw=()=>{
    const start=root._virtual?Math.max(0,Math.floor(root._scroll.scrollTop/40)-5):0,end=root._virtual?Math.min(rows.length,start+Math.ceil(root._scroll.clientHeight/40)+12):rows.length;
    const rendered=rows.slice(start,end).map((r,offset)=>{let tr=[...root._body.children].find(e=>e.dataset.index===String(r.index))||element('tr',{'data-index':r.index,id:root._id+'-'+r.index});tr.setAttribute('aria-rowindex',String(start+offset+2));tr.setAttribute('aria-selected',String(r.selected));tr.setAttribute('aria-disabled',String(!!r.disabled));tr.onclick=e=>{if(e.target.closest('input')||r.disabled)return;e.stopPropagation();root._table.focus({preventScroll:true});root._choose(r.index,e);};
      const cells=columns.map((c,j)=>{let td=[...tr.children].find(e=>e.dataset.column===c.path)||element('td',{'data-column':c.path});const cell=r.cells[j]||{text:''};td.textContent=cell.text;td.title=cell.text;td.classList.toggle('fx-table-cell-error',!!cell.error);return td;});
      if(p.ShowSelector){let td=tr.querySelector('[data-selector]');if(!td){td=element('td',{'data-selector':'true'});td.append(element('input',{type:'checkbox'}));}const input=td.firstChild;input.checked=!!r.selected;input.disabled=mode!=='Edit'||r.disabled;input.setAttribute('aria-label','Select row '+(r.index+1));input.onchange=e=>root._choose(r.index,e);cells.unshift(td);}reconcile(tr,cells);return tr;});
    const spacer=height=>{const row=element('tr',{'aria-hidden':'true'}),td=element('td',{colspan:columns.length+(p.ShowSelector?1:0),class:'fx-grid-spacer'});td.style.height=height+'px';row.append(td);return row;};
    reconcile(root._body,root._virtual?[spacer(start*40),...rendered,spacer((rows.length-end)*40)]:rendered);
    const current=rows.find(r=>r.index===node.latest);if(current&&root._body.querySelector('#'+root._id+'-'+current.index))root._table.setAttribute('aria-activedescendant',root._id+'-'+current.index);else root._table.removeAttribute('aria-activedescendant');
  };root._draw();root._empty.hidden=!!rows.length;return root;
}
