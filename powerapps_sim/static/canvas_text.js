'use strict';
function renderCanvasText(node,wrapper){
  const p=node.props||{},meta=node.native_text||{},fluent=node.family==='FluentV8/Label';
  let face=wrapper.querySelector(':scope > .fx-native-text');
  if(!face)face=element('div',{class:'fx-native-text'});
  face._model=node;
  face.dir=meta.rtl?'rtl':'ltr';
  face.style.cssText='width:100%;height:100%;margin:0;box-sizing:border-box;line-height:1.45;';
  face.style.whiteSpace=p.Wrap===false?'pre':'pre-wrap';
  face.style.overflow=meta.scroll?'auto':'hidden';
  face.style.fontFamily=p.Font||'Segoe UI, sans-serif';
  face.style.fontSize=fluent?(p.FontSize??10.5)+'pt':(p.Size??14)+'px';
  const weight=fluent?p.FontWeight:p.Weight;
  face.style.fontWeight=({normal:'400',regular:'400',medium:'500',semibold:'600',bold:'700',lighter:'300'})[String(weight||'').toLowerCase()]||'400';
  face.style.color=(fluent?p.Color:p.FontColor)||'#242424';
  face.style.fontStyle=p.FontItalic?'italic':'normal';
  face.style.textDecoration=[p.FontUnderline?'underline':'',p.FontStrikethrough?'line-through':''].filter(Boolean).join(' ');
  const align=String((fluent?p.Alignment:p.Align)||(fluent?'left':'Start')).toLowerCase();
  face.style.textAlign=align==='end'?'end':align==='start'?'start':align;
  for(const side of ['Top','Bottom'])face.style['padding'+side]=(p['Padding'+side]||0)+'px';
  if(fluent){face.style.paddingInlineStart=(p.PaddingStart||0)+'px';face.style.paddingInlineEnd=(p.PaddingEnd||0)+'px';}
  else for(const side of ['Left','Right'])face.style['padding'+side]=(p['Padding'+side]||0)+'px';
  wrapper.style.padding='0';wrapper.style.border='0';wrapper.style.background='transparent';
  if(!fluent){
    face.style.background=p.Fill||'transparent';face.style.borderStyle=(p.BorderStyle||'Solid').toLowerCase();
    face.style.borderWidth=(p.BorderThickness||0)+'px';face.style.borderColor=p.BorderColor||'transparent';
    const authored=new Set(meta.authored||[]);
    for(const corner of ['TopLeft','TopRight','BottomLeft','BottomRight'])face.style['border'+corner+'Radius']=(authored.has('BorderRadius'+corner)?p['BorderRadius'+corner]:p.BorderRadius||0)+'px';
  }
  // A separate text block preserves justification, newline wrapping and
  // scrollbar behavior; flex belongs to the outer face, not the line boxes.
  let block=face.querySelector(':scope > .fx-native-text-lines');
  if(!block)block=element('div',{class:'fx-native-text-lines'});
  block.textContent=p.Text??'';block.style.cssText='width:100%;flex-shrink:0;';
  reconcile(face,[block]);face.style.display='flex';face.style.flexDirection='column';
  const vertical=String((fluent?p.VerticalAlignment:p.VerticalAlign)||'Middle').toLowerCase();
  face.style.justifyContent=meta.scroll?'flex-start':vertical==='top'?'flex-start':vertical==='bottom'?'flex-end':'center';
  const disabled=node._effectiveMode!=='Edit'||!!face._pending||meta.busy;
  face.tabIndex=node.tab_stop&&!disabled?0:-1;
  face.removeAttribute('role');face.removeAttribute('aria-level');face.removeAttribute('aria-disabled');
  if(meta.heading){face.setAttribute('role','heading');face.setAttribute('aria-level',String(meta.heading));}
  else if(node.selectable)face.setAttribute('role','button');
  if(node.selectable)face.setAttribute('aria-disabled',String(disabled));
  face.style.cursor=node.selectable&&!disabled?'pointer':'default';
  face.onclick=event=>{
    const model=face._model;
    if(!model.selectable||model._effectiveMode!=='Edit'||face._pending||model.native_text?.busy||$('inspect-toggle').checked)return;
    event.stopPropagation();face._pending=!!model.native_text?.auto_disable;
    face.setAttribute('aria-busy',String(face._pending));face.setAttribute('aria-disabled',String(face._pending));
    emit(model,'OnSelect').finally(()=>{
      face._pending=false;face.setAttribute('aria-busy','false');face.setAttribute('aria-disabled',String(face._model._effectiveMode!=='Edit'||!!face._model.native_text?.busy));
    });
  };
  face.onkeydown=event=>{
    if(face._model.selectable&&face.tabIndex>=0&&!event.repeat&&['Enter',' '].includes(event.key)){
      event.preventDefault();face.click();
    }
  };
  return face;
}
