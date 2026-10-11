'use strict';
// Native tab navigation follows the server's stable visual DOM sequence.
let lastFocusRequest=null;
const focusableSelector='input,textarea,select,button,iframe,[tabindex]';
function ownFocusables(wrapper){return [...wrapper.querySelectorAll(focusableSelector)].filter(e=>e.closest('[data-path]')===wrapper);}
function restoreKeyboardContract(wrapper){for(const e of ownFocusables(wrapper)){if(e._emuOriginalTabIndex!==undefined){if(e._emuOriginalTabIndex===null)e.removeAttribute('tabindex');else e.setAttribute('tabindex',e._emuOriginalTabIndex);delete e._emuOriginalTabIndex;}}}
function applyKeyboardContract(wrapper,node){
  if(node.tab_stop===false||['Hidden','Disabled'].includes(node._effectiveMode)){
    for(const e of ownFocusables(wrapper)){e._emuOriginalTabIndex=e.getAttribute('tabindex');e.tabIndex=-1;}
  }
}
function settleFocus(previous){
  const request=state?.focus_request;
  if(request&&request.id!==lastFocusRequest&&!$('build-view').hidden&&!$('preview-pane').hidden&&!$('inspect-toggle').checked){
    const wrapper=elements.get(request.path);
    if(wrapper&&!wrapper.closest('[hidden]')){
      const target=ownFocusables(wrapper).find(e=>!e.disabled);
      if(target){lastFocusRequest=request.id;target.focus();return;}
    }
  }
  // Moving an existing DOM node can drop focus. Restore it only inside the preview.
  if(previous&&previous.isConnected&&document.activeElement===document.body&&!previous.disabled&&!previous.closest('[hidden]'))previous.focus({preventScroll:true});
}

function previewActiveElement(canvas){
  let active=document.activeElement;
  if(!canvas.contains(active))return null;
  while(active?.shadowRoot?.activeElement)active=active.shadowRoot.activeElement;
  return active;
}
