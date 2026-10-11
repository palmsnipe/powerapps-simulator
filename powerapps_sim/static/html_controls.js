'use strict';
// Python supplies a presentation fragment, never executable formula source.
// Shadow DOM keeps IDs/selectors and the editor's global table styles isolated.
function renderHtmlText(node,wrapper,mode){
  let host=wrapper.querySelector(':scope > .fx-html');
  if(!host){host=document.createElement('div');host.className='fx-html';host.attachShadow({mode:'open'});}
  host.style.cssText='position:relative;width:100%;height:100%;overflow:hidden;box-sizing:border-box;';
  const root=host.shadowRoot;
  if(host._html!==node.html){
    root.innerHTML='<style>:host{display:block;line-height:1.45} .content{position:relative;min-height:0;overflow-wrap:break-word} p,ul,ol,li,blockquote,h1,h2,h3,h4,h5,h6{margin:0;padding:0} ul,ol{list-style:none} table{border-collapse:collapse} img{max-width:100%} a{color:inherit;text-decoration:underline;cursor:pointer} pre{white-space:pre-wrap}</style><div class="content">'+(node.html||'')+'</div>';
    host._html=node.html;
  }
  host._node=node;host._mode=mode;
  for(const anchor of root.querySelectorAll('a[data-emu-link]'))anchor.tabIndex=['Hidden','Disabled'].includes(mode)?-1:0;
  if(!host._events){
  root.addEventListener("click",event=>{
    if($('inspect-toggle').checked){event.preventDefault();return;}
    const link=event.target.closest('a');
    event.stopPropagation();
    if(link){
      event.preventDefault();
      if(['Hidden','Disabled'].includes(host._mode))return;
      const href=link.dataset.emuLink||'';
      if(href.startsWith('#')&&href.length>1){
        const id=href.slice(1);const target=[...root.querySelectorAll('[id]')].find(e=>e.id===id);
        if(target)target.scrollIntoView({block:'nearest',inline:'nearest'});
      }
      return; // Hyperlinks never invoke the HtmlViewer's OnSelect.
    }
    if(host._node.selectable&&host._mode==='Edit')emit(host._node,'OnSelect');
  });
  root.addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.closest('a[data-emu-link]')){event.preventDefault();event.target.closest('a').click();}});
  host._events=true;
  }
  const p=node.props||{};
  wrapper.style.background=mode==='Disabled'?(p.DisabledFill||p.Fill||'transparent'):(p.Fill||'transparent');
  wrapper.style.borderColor=mode==='Disabled'?(p.DisabledBorderColor||p.BorderColor||'transparent'):(p.BorderColor||'transparent');
  wrapper.onpointerenter=()=>{if(mode!=='Disabled')wrapper.style.borderColor=p.HoverBorderColor||p.BorderColor||'transparent';};
  wrapper.onpointerleave=()=>{wrapper.style.borderColor=mode==='Disabled'?(p.DisabledBorderColor||p.BorderColor||'transparent'):(p.BorderColor||'transparent');};
  return host;
}
