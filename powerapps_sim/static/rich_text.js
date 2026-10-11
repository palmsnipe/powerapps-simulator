'use strict';
// The iframe isolates formatting and retains the browser's native undo stack.
// Only sanitized fragments enter its DOM; values/events stay authoritative in Python.
function renderRichText(node,wrapper,mode){
  let root=wrapper.querySelector(':scope > .fx-rich-text');
  if(!root){
    root=element('div',{class:'fx-rich-text'});
    const bar=element('div',{class:'fx-rich-toolbar',role:'toolbar'});
    const frame=element('iframe',{class:'fx-rich-frame',sandbox:'allow-same-origin'});
    const note=element('div',{class:'fx-rich-note',role:'status'});note.hidden=true;
    root._frame=frame;root._bar=bar;root._note=note;root._server=null;root._draft=null;
    root._saveRange=()=>{const selection=frame.contentDocument?.getSelection();if(selection?.rangeCount&&frame.contentDocument.body.contains(selection.anchorNode))root._range=selection.getRangeAt(0).cloneRange();};
    root._restoreRange=()=>{const doc=frame.contentDocument;if(!doc?.body||!root._range||!doc.body.contains(root._range.commonAncestorContainer))return;doc.body.focus();const sel=doc.getSelection();sel.removeAllRanges();sel.addRange(root._range);};
    root._send=()=>{
      const body=frame.contentDocument?.body;if(!body||root._mode!=='Edit'||$('inspect-toggle').checked||root._composing)return;
      const html=body.innerHTML,token=root._reset;
      if(html===root._sent)return;root._sent=html;root._draft=html;
      enqueue(async()=>{
        if(!root.isConnected||root._reset!==token||root._mode!=='Edit'){if(root._sent===html)root._sent=null;return;}
        let reply;try{reply=await api('/api/event',{path:root._node.path,name:'OnChange',value:{html,reset_token:token}});}catch(error){if(root._sent===html)root._sent=null;throw error;}
        state=reply;renderState();if(selectedPath)await inspect(selectedPath);
      });
    };
    root._command=(command,value)=>{
      const doc=frame.contentDocument;if(!doc?.body||root._mode!=='Edit'||$('inspect-toggle').checked)return;
      root._restoreRange();doc.body.focus();
      if(!doc.queryCommandSupported(command)){
        note.hidden=false;note.textContent=command+' is unavailable in this browser';emit(root._node,'OnEditorIssue',{command});return;
      }
      doc.execCommand('styleWithCSS',false,true);
      doc.execCommand(command,false,value??null);root._saveRange();root._send();
    };
    const controls=[['Bold','B','bold'],['Italic','I','italic'],['Underline','U','underline'],['Bulleted list','•','insertUnorderedList'],['Numbered list','1.','insertOrderedList'],['Clear formatting','Tx','removeFormat'],['Remove link','↛','unlink'],['Undo','↶','undo'],['Redo','↷','redo']];
    for(const [label,glyph,command] of controls){
      const button=element('button',{type:'button',title:label},glyph);button.dataset.label=label;button.dataset.command=command;
      button.onpointerdown=event=>{root._saveRange();event.preventDefault();};
      button.onclick=event=>{event.stopPropagation();root._command(command);};bar.append(button);
    }
    const size=element('select');size.dataset.label='Text size';
    for(const [value,label] of [[1,'10'],[2,'13'],[3,'16'],[4,'18'],[5,'24'],[6,'32'],[7,'48']])size.append(element('option',{value:String(value)},label));size.value='3';
    size.onpointerdown=root._saveRange;size.onchange=()=>root._command('fontSize',size.value);bar.append(size);
    for(const [label,command,initial] of [['Text color','foreColor','#242424'],['Highlight color','hiliteColor','#fff59d']]){
      const color=element('input',{type:'color',value:initial,title:label});color.dataset.label=label;color.onpointerdown=root._saveRange;color.onchange=()=>root._command(command,color.value);bar.append(color);
    }
    const link=element('button',{type:'button',title:'Insert link'},'↗');link.dataset.label='Insert link';
    const dialog=element('dialog',{class:'fx-rich-link-dialog'}),form=element('form');
    const heading=element('h2',{},'Insert link'),label=element('label',{},'URL'),url=element('input',{type:'text',placeholder:'https://example.test or #section'});
    label.append(url);const actions=element('div',{class:'dialog-actions'}),cancel=element('button',{type:'button'},'Cancel'),apply=element('button',{type:'submit',class:'primary'},'Insert link');actions.append(cancel,apply);form.append(heading,label,actions);dialog.append(form);
    link.onpointerdown=root._saveRange;link.onclick=event=>{event.stopPropagation();if(root._mode!=='Edit')return;root._dialogToken=root._reset;dialog.showModal();url.focus();};
    cancel.onclick=()=>dialog.close();form.onsubmit=event=>{
      event.preventDefault();const href=url.value.trim();if(!href||/[\x00-\x20\x7f\]/.test(href)||/^(?!https?:|mailto:|tel:|#)[^/]*:/i.test(href)){url.setCustomValidity('Enter an HTTP, mail, telephone or fragment link');url.reportValidity();return;}
      url.setCustomValidity('');dialog.close();if(root._dialogToken===root._reset)root._command('createLink',href);
    };url.oninput=()=>url.setCustomValidity('');bar.append(link);
    const insert=async(html,range,token)=>{
      const cleaned=await api('/api/richtext/sanitize',{path:root._node.path,html,reset_token:token});
      if(cleaned.stale||root._reset!==token||!root.isConnected||root._mode!=='Edit')return;
      root._range=range;root._command('insertHTML',cleaned.html);
    };
    frame.onload=()=>{
      const doc=frame.contentDocument,body=doc.body;
      body.innerHTML=root._draft??'';root._ready=true;
      body.oninput=()=>{root._saveRange();root._send();};
      body.oncompositionstart=()=>root._composing=true;
      body.oncompositionend=()=>{root._composing=false;root._send();};
      doc.addEventListener('selectionchange',root._saveRange);
      doc.addEventListener('click',event=>{if(event.target.closest('a'))event.preventDefault();if($('inspect-toggle').checked){inspect(root._node.path).catch(e=>status(e.message,true));}});
      body.onpaste=event=>{
        event.preventDefault();if(root._mode!=='Edit'||$('inspect-toggle').checked)return;root._saveRange();const token=root._reset,range=root._range?.cloneRange();
        const data=event.clipboardData;let html=data.getData('text/html');
        if(!html){const bitmap=[...data.items].find(i=>i.kind==='file'&&/^image\/(png|jpeg|gif|webp)$/.test(i.type));
          if(bitmap){const reader=new FileReader();reader.onload=()=>insert('<img src="'+reader.result+'">',range,token).catch(e=>status(e.message,true));reader.readAsDataURL(bitmap.getAsFile());return;}
          html=data.getData('text/plain').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replace(/\r\n|\r|\n/g,'<br>');}
        insert(html,range,token).catch(e=>status(e.message,true));
      };
      // Drop native HTML/URL payloads through the same Python sanitizer.
      body.ondragover=event=>event.preventDefault();body.ondrop=event=>{event.preventDefault();if(root._mode!=='Edit')return;root._saveRange();const html=event.dataTransfer.getData('text/html')||event.dataTransfer.getData('text/plain').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');insert(html,root._range?.cloneRange(),root._reset).catch(e=>status(e.message,true));};
      body.onkeydown=event=>{if(event.altKey&&event.key==='0'){event.preventDefault();note.hidden=false;note.textContent='Ctrl/Cmd+B bold · I italic · U underline · Z undo · Shift+Z redo';}};
      root._present();
    };
    root._present=()=>{
      const body=frame.contentDocument?.body;if(!root._ready||!body)return;
      body.contentEditable=String(root._mode==='Edit'&&!$('inspect-toggle').checked);
      body.spellcheck=!!root._node.props.EnableSpellCheck;
      body.setAttribute('role','textbox');body.setAttribute('aria-multiline','true');body.setAttribute('aria-label',root._label);
      body.setAttribute('aria-readonly',String(root._mode!=='Edit'));body.setAttribute('aria-disabled',String(root._mode==='Disabled'));
      body.tabIndex=root._node.tab_stop===false||['Hidden','Disabled'].includes(root._mode)?-1:0;
      body.style.fontSize=(Number(root._node.props.Size)||14)+'px';
    };
    frame.srcdoc='<!doctype html><html><head><meta charset="utf-8"><style>html{background:transparent}body{margin:0;padding:10px;font-family:"Segoe UI",sans-serif;font-size:14px;color:#242424;line-height:1.35;min-height:calc(100vh - 20px);box-sizing:border-box;overflow-wrap:break-word}body:focus{outline:none}p{margin:0 0 8px}ul,ol{padding-left:24px}img{max-width:100%}a{color:#0f6cbd}table{border-collapse:collapse}</style></head><body></body></html>';
    reconcile(root,[bar,frame,note,dialog]);
  }
  root._node=node;root._mode=mode;root._label=node.props.AccessibleLabel||node.name;
  const server=String(node.value??''),token=node.text_reset;
  if(root._reset!==token){root._reset=token;root._draft=server;root._sent=null;root._range=null;root._note.hidden=true;if(root._ready)root._frame.contentDocument.body.innerHTML=server;}
  else if(mode!=='Edit'||root._draft===root._server){if(mode!=='Edit')root._sent=null;if(root._draft!==server&&root._ready)root._frame.contentDocument.body.innerHTML=server;root._draft=server;}
  root._server=server;
  root._bar.setAttribute('aria-label','Formatting '+root._label);
  for(const control of root._bar.querySelectorAll('button,input,select')){control.disabled=mode!=='Edit'||$('inspect-toggle').checked;control.setAttribute('aria-label',control.dataset.label+' '+root._label);}
  root._frame.title=root._label;root._frame.tabIndex=node.tab_stop===false||['Hidden','Disabled'].includes(mode)?-1:0;root._present();
  return root;
}
