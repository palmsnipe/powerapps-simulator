'use strict';
// Server-owned loading state. Scrolling never invokes app behavior formulas.
let galleryFrame=null;
function retainedGalleryElement(path){
  let position=0,found=false;
  while((position=path.indexOf('/row:',position))!==-1){
    found=true;const gallery=path.slice(0,position),start=position+5,end=path.indexOf('/',start);
    const key=path.slice(start,end===-1?undefined:end);
    if(!(state.gallery_instances?.[gallery]||[]).includes(key))return false;
    position=start;
  }
  return found;
}
function renderGallery(node,wrapper,used,disabled){
  const p=node.props||{},loading=node.loading||{};
  const horizontal=node.variant==='Horizontal',wrap=Math.max(1,Math.floor(p.WrapCount||1)),size=Math.max(1,p.TemplateSize||0),gap=Math.max(0,p.TemplatePadding||0);
  wrapper.style.overflow='auto';wrapper.classList.toggle('fx-hide-scrollbar',p.ShowScrollbar===false);
  wrapper.setAttribute('role','list');wrapper.setAttribute('aria-label',p.AccessibleLabel||node.name);
  wrapper.setAttribute('aria-busy',String(!!loading.waiting));
  let surface=wrapper.querySelector(':scope > .fx-gallery-surface');
  if(!surface)surface=element('div',{class:'fx-gallery-surface'});
  surface.style.position='relative';surface.style.minWidth='0';surface.style.minHeight='0';
  surface.style.width=(horizontal?loading.length??0:Math.max(0,p.Width||0))+'px';
  surface.style.height=(horizontal?Math.max(0,p.Height||0):loading.length??0)+'px';
  const cross=Math.max(0,((horizontal?p.Height:p.Width)-gap*(wrap-1))/wrap);
  const cells=(node.rows||[]).map(row=>{
    const key=node.path+'/row:'+row.key;used.add(key);let cell=elements.get(key);
    if(!cell){cell=element('div',{class:'fx-row'});elements.set(key,cell);}
    const group=Math.floor(row.index/wrap),lane=row.index%wrap;
    Object.assign(cell.style,{position:'absolute',left:(horizontal?group*(size+gap):lane*(cross+gap))+'px',top:(horizontal?lane*(cross+gap):group*(size+gap))+'px',width:(horizontal?size:cross)+'px',height:(horizontal?cross:size)+'px',minWidth:'0',minHeight:'0',background:row.props?.TemplateFill||'transparent'});
    cell.setAttribute('role','listitem');cell.setAttribute('aria-setsize',String(loading.total??node.rows.length));cell.setAttribute('aria-posinset',String(row.index+1));
    cell.setAttribute('aria-label',row.props?.ItemAccessibleLabel||`Row ${row.index+1}`);
    cell.setAttribute('aria-current',String(!!row.selected));cell.tabIndex=!disabled&&p.Selectable!==false&&!row.error?0:-1;
    const select=()=>{if(!disabled&&p.Selectable!==false&&!row.error&&!$('inspect-toggle').checked)emit(node,'OnSelect',{row_key:row.key,items_token:node.items_token});};
    cell.onclick=event=>{if(event.target.closest('.fx-control')!==wrapper||$('inspect-toggle').checked)return;event.stopPropagation();select();};
    cell.onkeydown=event=>{if(event.target===cell&&!event.repeat&&['Enter',' '].includes(event.key)){event.preventDefault();select();}};
    cell.classList.toggle('fx-row-error',!!row.error);
    reconcile(cell,row.error?[element('div',{class:'fx-error',role:'alert'},'Power Fx error: '+row.error.Message)]:row.children.map(c=>renderNode(c,node,used)));
    return cell;
  });
  reconcile(surface,cells);
  const content=[surface];
  if(loading.waiting&&['Controls','Data'].includes(p.LoadingSpinner)){
    const spinner=element('div',{class:'fx-gallery-loading',role:'status','aria-label':'Loading items'},'Loading…');
    Object.assign(spinner.style,{position:'absolute',left:'12px',top:'12px',color:p.LoadingSpinnerColor||'#0f6cbd'});content.push(spinner);
  }
  wrapper.onscroll=scheduleGalleryViewports;
  // Restore/reset after reconciliation, when the full scroll surface exists.
  if(wrapper._galleryReset!==node.reset_token)wrapper._galleryResetPending=true;
  wrapper._galleryReset=node.reset_token;
  requestAnimationFrame(()=>{if(wrapper._galleryResetPending){wrapper._galleryResetPending=false;wrapper.scrollTop=0;wrapper.scrollLeft=0;scheduleGalleryViewports();}});
  return content;
}
function galleryViewport(wrapper){
  const node=wrapper._node,p=node.props||{},horizontal=node.variant==='Horizontal';
  const rect=wrapper.getBoundingClientRect(),logical=horizontal?p.Width:p.Height;
  const span=horizontal?rect.width:rect.height,scale=logical>0?span/logical:0;
  if(scale<=0||!wrapper.isConnected||wrapper.closest('[hidden]'))return null;
  let left=Math.max(rect.left,0),right=Math.min(rect.right,window.innerWidth),top=Math.max(rect.top,0),bottom=Math.min(rect.bottom,window.innerHeight);
  for(let parent=wrapper.parentElement;parent;parent=parent.parentElement){
    const style=getComputedStyle(parent),bounds=parent.getBoundingClientRect();
    if(['auto','scroll','hidden','clip'].includes(style.overflowX)){left=Math.max(left,bounds.left);right=Math.min(right,bounds.right);}
    if(['auto','scroll','hidden','clip'].includes(style.overflowY)){top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom);}
  }
  if(right<=left||bottom<=top)return null;
  const scroll=horizontal?wrapper.scrollLeft:wrapper.scrollTop;
  return {offset:Math.max(0,scroll+(horizontal?left-rect.left:top-rect.top)/scale),extent:Math.min(logical,(horizontal?right-left:bottom-top)/scale),viewport_token:node.loading.viewport_token};
}
function scheduleGalleryViewports(){
  if(galleryFrame!==null)return;
  galleryFrame=requestAnimationFrame(()=>{
    galleryFrame=null;
    for(const wrapper of elements.values()){
      if(wrapper._node?.family!=='Gallery'||!wrapper._node.loading)continue;
      const value=galleryViewport(wrapper);if(!value)continue;
      // Rounding prevents subpixel layout jitter from triggering an endless cycle.
      value.offset=Math.round(value.offset*100)/100;value.extent=Math.round(value.extent*100)/100;
      const signature=JSON.stringify(value);if(signature===wrapper._galleryViewport)continue;
      wrapper._galleryViewport=signature;
      enqueue(async()=>{
        if(!wrapper.isConnected||signature!==wrapper._galleryViewport)return;
        try{state=await api('/api/event',{path:wrapper._node.path,name:'OnViewport',value});renderState();}
        catch(error){wrapper._galleryViewport=null;throw error;}
      });
    }
  });
}
window.addEventListener('scroll',scheduleGalleryViewports,true);
window.addEventListener('resize',scheduleGalleryViewports);
