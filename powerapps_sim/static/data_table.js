'use strict';
let dataTableId=0;
function renderDataTable(node,wrapper,mode){
  let root=wrapper.querySelector(':scope > .fx-data-table');
  if(!root){
    root=element('div',{class:'fx-data-table'});root._widths=new Map();root._id='emu-table-'+(++dataTableId);
    root._table=element('table',{role:'grid',tabindex:'0'});root._cols=element('colgroup');root._head=element('thead');root._body=element('tbody');root._empty=element('div',{class:'fx-table-empty'});
    root._table.append(root._cols,root._head,root._body);root.append(root._table,root._empty);
    root._select=(index,column)=>{const m=root._model;if(m.mode!=='Edit'||$('inspect-toggle').checked)return;const value={index,items_token:m.node.items_token};if(column)value.column=column;emit(m.node,'OnSelect',value);};
    root._table.onkeydown=e=>{const m=root._model,rows=m.node.rows||[];if(m.mode==='Disabled'||$('inspect-toggle').checked||e.target!==root._table||!rows.length)return;
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const current=rows.findIndex(r=>r.selected);let i=e.key==='Home'?0:e.key==='End'?rows.length-1:Math.max(0,Math.min(rows.length-1,current+(e.key==='ArrowDown'?1:-1)));
        const step=e.key==='ArrowUp'||e.key==='End'?-1:1;while(rows[i]?.disabled&&i+step>=0&&i+step<rows.length)i+=step;
        if(!rows[i]?.disabled){root._select(rows[i].index);root._body.children[i]?.scrollIntoView({block:'nearest',inline:'nearest'});}
      }
    };
  }
  const p=node.props||{},columns=node.columns||[],rows=node.rows||[];root._model={node,mode};root.dataset.mode=mode;
  root._table.setAttribute('aria-label',p.AccessibleLabel||node.name);root._table.setAttribute('aria-readonly','true');root._table.setAttribute('aria-disabled',String(mode==='Disabled'));
  root.style.setProperty('--table-heading-fill',p.HeadingFill||'#0f6cbd');root.style.setProperty('--table-heading-color',p.HeadingColor||'white');
  root.style.setProperty('--table-selected-fill',p.SelectedFill||'#e1edf8');root.style.setProperty('--table-selected-color',p.SelectedColor||'#242424');
  root.style.setProperty('--table-hover-fill',p.HoverFill||'#f2f2f2');root.style.setProperty('--table-hover-color',p.HoverColor||'#242424');
  const live=new Set(columns.map(c=>c.path));for(const key of root._widths.keys())if(!live.has(key))root._widths.delete(key);
  const cols=columns.map(c=>{let col=[...root._cols.children].find(e=>e.dataset.column===c.path)||element('col',{'data-column':c.path});let saved=root._widths.get(c.path);if(saved?.base!==c.width){saved={base:c.width,width:c.width};root._widths.set(c.path,saved);}col.style.width=saved.width+'px';return col;});
  reconcile(root._cols,cols);
  const row=root._head.firstChild||element('tr');
  const headings=columns.map(c=>{
    let th=[...row.children].find(e=>e.dataset.column===c.path);if(!th){th=element('th',{'data-column':c.path,scope:'col'});th.append(element('span'),element('span',{class:'fx-table-resize',role:'separator',tabindex:'0','aria-orientation':'vertical'}));}
    th.firstChild.textContent=c.header;th.style.fontFamily=(p.HeadingFont||p.Font||'Segoe UI')+', Arial, sans-serif';th.style.fontSize=(p.HeadingSize??14)+'px';th.style.fontWeight={Bold:'700',Semibold:'600',Normal:'400'}[p.HeadingFontWeight]||'600';
    const handle=th.lastChild;handle.setAttribute('aria-label','Resize '+c.header);handle.setAttribute('aria-valuenow',String(root._widths.get(c.path).width));
    const resize=width=>{const saved=root._widths.get(c.path);saved.width=Math.max(48,width);cols[columns.indexOf(c)].style.width=saved.width+'px';root._table.style.width=columns.reduce((n,col)=>n+root._widths.get(col.path).width,0)+'px';handle.setAttribute('aria-valuenow',String(saved.width));};
    handle.onkeydown=e=>{if(root._model.mode==='Disabled'||$('inspect-toggle').checked)return;if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();e.stopPropagation();resize(root._widths.get(c.path).width+(e.key==='ArrowRight'?20:-20));}};
    handle.onpointerdown=e=>{if(root._model.mode==='Disabled'||$('inspect-toggle').checked)return;e.preventDefault();e.stopPropagation();handle.setPointerCapture(e.pointerId);const start=e.clientX,width=root._widths.get(c.path).width,scale=wrapper.getBoundingClientRect().width/(wrapper.offsetWidth||1);handle.onpointermove=move=>resize(width+(move.clientX-start)/(scale||1));handle.onpointerup=()=>{handle.onpointermove=null;};handle.onlostpointercapture=()=>{handle.onpointermove=null;};};
    return th;
  });reconcile(row,headings);reconcile(root._head,[row]);
  const rendered=rows.map(r=>{
    let tr=[...root._body.children].find(e=>e.dataset.index===String(r.index))||element('tr',{'data-index':r.index,id:root._id+'-'+r.index});
    tr.setAttribute('aria-selected',String(r.selected));tr.setAttribute('aria-disabled',String(!!r.disabled));
    const cells=columns.map((c,j)=>{let td=[...tr.children].find(e=>e.dataset.column===c.path)||element('td',{'data-column':c.path});const cell=r.cells[j]||{text:''},interactive=c.hyperlink||c.interactive;
      let value=td.firstChild;if(!value||value.tagName!==(interactive?'BUTTON':'SPAN')){value=element(interactive?'button':'span');td.replaceChildren(value);}value.textContent=cell.text;value.title=cell.text;value.className=cell.error?'fx-table-cell-error':'';
      if(interactive){value.type='button';value.classList.toggle('fx-table-hyperlink',!!c.hyperlink);value.tabIndex=r.selected?0:-1;value.disabled=mode!=='Edit'||c.mode!=='Edit'||!!r.disabled||!!cell.error;value.onclick=e=>{e.stopPropagation();root._select(r.index,c.path);};}
      td.onclick=e=>{if($('inspect-toggle').checked||r.disabled)return;e.stopPropagation();root._table.focus({preventScroll:true});root._select(r.index,c.path);};return td;
    });reconcile(tr,cells);return tr;
  });reconcile(root._body,rendered);root._table.style.width=columns.reduce((n,c)=>n+root._widths.get(c.path).width,0)+'px';
  const selected=rows.find(r=>r.selected);if(selected)root._table.setAttribute('aria-activedescendant',root._id+'-'+selected.index);else root._table.removeAttribute('aria-activedescendant');
  root._empty.textContent=p.NoDataText||'';root._empty.hidden=!!rows.length;return root;
}
