'use strict';
const badgePalette={Neutral:['#424242','#f0f0f0'],Highlight:['#0f6cbd','#ebf3fc'],Informative:['#0f548c','#e8f4ff'],Positive:['#107c10','#dff6dd'],Attention:['#8a3707','#fff4ce'],Caution:['#835b00','#fff4ce'],Urgent:['#a4262c','#fde7e9'],Critical:['#c50f1f','#fde7e9']};
function statusTypography(face,p){
  face.style.fontFamily=(p.Font||'Segoe UI')+', Arial, sans-serif';face.style.fontSize=(p.Size??14)+'px';
  face.style.fontWeight={Semibold:'600',Bold:'700',Normal:'400',Lighter:'300'}[p.FontWeight]||'400';
  face.style.fontStyle=p.Italic?'italic':'normal';
  face.style.textDecoration=[p.Underline?'underline':'',p.Strikethrough?'line-through':''].filter(Boolean).join(' ');
  if(p.ContentLanguage)face.lang=p.ContentLanguage;else face.removeAttribute('lang');
}
function renderBadge(node,wrapper){
  const p=node.props||{},interactive=!!node.selectable,tag=interactive?'button':'span',authored=new Set(node.status_authored||[]);
  let face=wrapper.querySelector(':scope > .fx-badge');
  if(face?.tagName.toLowerCase()!==tag)face=null;
  if(!face)face=element(tag,{class:'fx-badge'});
  const content=node.badge_text??String(p.Content??'');
  if(interactive){face.type='button';face.disabled=node._effectiveMode!=='Edit';face.setAttribute('aria-label',p.AccessibleLabel||content||node.name);}
  else{face.setAttribute('role','img');face.setAttribute('aria-label',p.AccessibleLabel||content||node.name);}
  face.onclick=interactive?event=>{if(node._effectiveMode!=='Edit'||$('inspect-toggle').checked)return;event.stopPropagation();emit(node,'OnSelect');}:null;
  const glyph=node.icon?.symbol?iconGlyph(node.icon):null,text=element('span',{},content);
  const parts=[...(glyph?[glyph]:[]),...(content!==''?[text]:[])];
  reconcile(face,p.IconPosition==='After'?parts.reverse():parts);
  const [base,tint]=badgePalette[p.Intent]||badgePalette.Positive,brand=p.Intent==='Highlight'?(p.BasePaletteColor||base):base;
  const appearance=p.Appearance||'Tint';
  face.style.color=p.Color??(appearance==='Filled'?'#fff':brand);
  face.style.background=p.Fill??(appearance==='Filled'?brand:appearance==='Tint'?(p.Intent==='Highlight'?`color-mix(in srgb, ${brand} 12%, white)`:tint):'transparent');
  face.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();
  face.style.borderWidth=(authored.has('BorderThickness')?(p.BorderThickness??0):appearance==='Outline'?1:0)+'px';
  face.style.borderColor=p.BorderColor||(appearance==='Outline'?brand:'transparent');
  for(const corner of ['TopLeft','TopRight','BottomLeft','BottomRight'])face.style['border'+corner+'Radius']=authored.has('Radius'+corner)?(p['Radius'+corner]??0)+'px':p.Shape==='Square'?'0px':p.Shape==='Rounded'?'4px':'9999px';
  for(const direction of ['Top','Bottom','Left','Right'])face.style['padding'+direction]=(p['Padding'+direction]??0)+'px';
  face.style.justifyContent={Left:'flex-start',Center:'center',Right:'flex-end',Justify:'space-between'}[p.Align]||'center';
  face.style.alignItems={Top:'flex-start',Middle:'center',Bottom:'flex-end'}[p.VerticalAlign]||'center';
  face.style.opacity=node._effectiveMode==='Disabled'?'.4':'1';statusTypography(face,p);
  wrapper.style.padding='0';wrapper.style.border='0';wrapper.style.background='transparent';
  return face;
}
// One presentation-only flyout at a time. Python owns Content and OnSelect;
// hover never executes a behavior formula or changes simulated app variables.
let informationFlyout=null,informationSerial=0;
function closeInformation(returnFocus=false){
  const current=informationFlyout;if(!current)return;
  clearTimeout(current.leaveTimer);current.face.setAttribute('aria-expanded','false');current.face.removeAttribute('aria-controls');
  current.panel.remove();informationFlyout=null;
  if(returnFocus&&current.face.isConnected&&!current.face.disabled)current.face.focus({preventScroll:true});
}
function positionInformation(){
  const current=informationFlyout;if(!current)return;
  const box=current.face.getBoundingClientRect(),panel=current.panel,padding=8;
  let visible={left:Math.max(0,box.left),top:Math.max(0,box.top),right:Math.min(innerWidth,box.right),bottom:Math.min(innerHeight,box.bottom)};
  for(let ancestor=current.face.parentElement;ancestor;ancestor=ancestor.parentElement){
    const style=getComputedStyle(ancestor),bounds=ancestor.getBoundingClientRect();
    if(['hidden','clip','auto','scroll'].includes(style.overflowX)){visible.left=Math.max(visible.left,bounds.left);visible.right=Math.min(visible.right,bounds.right);}
    if(['hidden','clip','auto','scroll'].includes(style.overflowY)){visible.top=Math.max(visible.top,bounds.top);visible.bottom=Math.min(visible.bottom,bounds.bottom);}
  }
  if(visible.right<=visible.left||visible.bottom<=visible.top){closeInformation();return;}
  panel.style.maxWidth=Math.max(1,Math.min(360,innerWidth-2*padding))+'px';
  panel.style.maxHeight=Math.max(1,innerHeight-2*padding)+'px';
  const width=panel.offsetWidth,height=panel.offsetHeight;
  panel.style.left=Math.max(padding,Math.min(box.left,innerWidth-width-padding))+'px';
  const top=box.bottom+6+height<=innerHeight-padding?box.bottom+6:Math.max(padding,box.top-height-6);
  panel.style.top=top+'px';
}
function updateInformation(){
  const current=informationFlyout;if(!current)return;
  const node=current.wrapper._node;
  if(!current.face.isConnected||current.wrapper.closest('[hidden]')||node?._effectiveMode!=='Edit'||$('inspect-toggle').checked||$('preview-pane').hidden||$('build-view').hidden){closeInformation();return;}
  const p=node.props||{};
  current.panel.setAttribute('aria-label',p.AccessibleLabel||node.name);
  statusTypography(current.panel,p);current.panel.style.color=p.Color||'#242424';
  if(current.html!==node.info_html){
    current.content.innerHTML='<style>:host{display:block;overflow-wrap:anywhere;white-space:pre-wrap;line-height:1.45} .content{position:relative;overflow:hidden} img{max-width:100%} pre{white-space:pre-wrap} table{border-collapse:collapse} a{color:inherit;text-decoration:underline}</style><div class="content">'+(node.info_html||'')+'</div>';
    current.html=node.info_html;
  }
  positionInformation();
}
function scheduleInformationClose(){
  const current=informationFlyout;if(!current||current.pinned)return;
  clearTimeout(current.leaveTimer);current.leaveTimer=setTimeout(()=>{if(informationFlyout===current&&!current.face.matches(':hover')&&!current.panel.matches(':hover')&&!current.panel.contains(document.activeElement))closeInformation();},180);
}
function openInformation(wrapper,face,pinned){
  if(informationFlyout?.wrapper!==wrapper)closeInformation();
  if(!informationFlyout){
    const panel=element('div',{class:'fx-information-flyout',role:'dialog',tabindex:'-1',id:'emu-information-'+(++informationSerial)});
    const host=element('div');host.attachShadow({mode:'open'});panel.append(host);document.body.append(panel);
    informationFlyout={panel,content:host.shadowRoot,wrapper,face,pinned:false,html:null};
    panel.addEventListener('pointerenter',()=>clearTimeout(informationFlyout?.leaveTimer));
    panel.addEventListener('pointerleave',scheduleInformationClose);
    host.shadowRoot.addEventListener('click',event=>{const anchor=event.target.closest('a');if(!anchor)return;event.preventDefault();const href=anchor.dataset.emuLink||'';if(href.startsWith('#')){const target=[...host.shadowRoot.querySelectorAll('[id]')].find(e=>e.id===href.slice(1));target?.scrollIntoView({block:'nearest'});}});
  }
  informationFlyout.pinned=informationFlyout.pinned||pinned;
  clearTimeout(informationFlyout.leaveTimer);face.setAttribute('aria-expanded','true');face.setAttribute('aria-controls',informationFlyout.panel.id);
  updateInformation();
}
function renderInformation(node,wrapper){
  const p=node.props||{};
  let face=wrapper.querySelector(':scope > .fx-information');if(!face)face=element('button',{class:'fx-information',type:'button'});
  face.disabled=node._effectiveMode!=='Edit';face.setAttribute('aria-label',p.AccessibleLabel||node.name);face.setAttribute('aria-haspopup','dialog');
  face.setAttribute('aria-expanded',String(informationFlyout?.face===face));face.style.color=p.IconColor||'#424242';
  const glyph=node.icon?iconGlyph(node.icon):null;reconcile(face,glyph?[glyph]:[]);
  face.onpointerenter=()=>{if(node._effectiveMode==='Edit'&&!$('inspect-toggle').checked)openInformation(wrapper,face,false);};
  face.onpointerleave=scheduleInformationClose;
  face.onclick=event=>{
    if(node._effectiveMode!=='Edit'||$('inspect-toggle').checked)return;event.stopPropagation();
    if(informationFlyout?.face===face&&informationFlyout.pinned)closeInformation();else openInformation(wrapper,face,true);
    emit(node,'OnSelect');
  };
  return face;
}
document.addEventListener('pointerdown',event=>{const current=informationFlyout;if(current&&!current.panel.contains(event.target)&&!current.wrapper.contains(event.target))closeInformation();},true);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&informationFlyout){event.preventDefault();event.stopPropagation();closeInformation(true);}},true);
window.addEventListener('resize',positionInformation);
document.addEventListener('scroll',positionInformation,true);
// Pane/view switches can hide the preview without another runtime render.
new MutationObserver(()=>{if(informationFlyout)updateInformation();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['hidden']});
