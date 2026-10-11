'use strict';
// Decoding stays in HTML media elements; intent and Power Fx callbacks stay in Python.
const canvasMedia=new Map();
function mediaObservation(entry,operation,extra={}){
  if(!entry.token||state?.inspection||$('inspect-toggle').checked)return;
  const token=entry.token,path=entry.path;
  const boundary=['play','pause','end'].includes(operation)?{}:null;
  if(boundary)entry.pending=boundary;
  enqueue(async()=>{
    try{
      if(canvasMedia.get(path)!==entry||entry.token!==token)return;
      state=await api('/api/event',{path,name:'OnMedia',value:{token,operation,...extra}});
    }finally{if(boundary&&entry.pending===boundary)entry.pending=null;}
    renderState();
  });
}
function renderMedia(node,wrapper,mode){
  let entry=canvasMedia.get(node.path);
  if(!entry){
    const player=element(node.family==='Video'?'video':'audio',{class:'fx-media-player',preload:'metadata',playsinline:''});
    entry={path:node.path,player,token:'',source:'',lastTime:-1,node};canvasMedia.set(node.path,entry);
    player.onloadedmetadata=()=>{if(Number.isFinite(player.duration))mediaObservation(entry,'metadata',{duration:player.duration});};
    player.onplay=()=>mediaObservation(entry,'play');
    player.onpause=()=>{if(!player.ended)mediaObservation(entry,'pause',{time:player.currentTime});};
    player.onended=()=>mediaObservation(entry,'end',{time:player.currentTime});
    player.ontimeupdate=()=>{
      if(player.ended||!Number.isFinite(player.currentTime)||Math.abs(player.currentTime-entry.lastTime)<0.2)return;
      entry.lastTime=player.currentTime;mediaObservation(entry,'time',{time:player.currentTime});
    };
    player.onseeked=()=>{entry.lastTime=player.currentTime;mediaObservation(entry,'time',{time:player.currentTime});};
    player.onerror=()=>mediaObservation(entry,'issue',{message:'The browser cannot decode this local media clip'});
    player.onclick=e=>{if(!$('inspect-toggle').checked)e.stopPropagation();};
  }
  entry.node=node;entry.mode=mode;
  const player=entry.player,p=node.props,m=node.media||{};
  player.controls=p.ShowControls===true&&mode==='Edit';player.loop=false;
  player.setAttribute('aria-label',p.AccessibleLabel||node.name);
  player.tabIndex=mode==='Edit'&&p.ShowControls!==false?0:-1;
  if(node.family==='Video'){
    player.style.objectFit={Fit:'contain',Fill:'cover',Stretch:'fill',Center:'none'}[p.ImagePosition]||'contain';
    const poster=p.Image||'';player.poster=/^(\/api\/asset\/|data:image\/)/.test(poster)?poster:'';
    const captions=p.ClosedCaptionsUrl||'';
    let track=player.querySelector('track');
    if(captions.startsWith('/api/asset/')){
      if(!track){track=element('track',{kind:'captions',label:'Captions',srclang:'en'});player.append(track);}
      if(track.getAttribute('src')!==captions)track.src=captions;
    }else track?.remove();
  }
  const changed=entry.token!==m.token;
  entry.token=m.token||'';
  if(entry.source!==(m.source||'')){
    entry.source=m.source||'';entry.lastTime=-1;
    if(entry.source)player.src=entry.source;else{player.removeAttribute('src');player.load();}
  }
  if(changed&&player.readyState>=1){
    if(Number.isFinite(player.duration))mediaObservation(entry,'metadata',{duration:player.duration});
    if(Number.isFinite(m.time)&&Math.abs(player.currentTime-m.time)>0.05)player.currentTime=m.time;
  }
  wrapper._cleanup=()=>{
    let background=$('media-background');
    if(!background){background=element('div',{id:'media-background',hidden:''});document.body.append(background);}
    background.append(player);
  };
  return player;
}
function settleCanvasMedia(){
  const states=new Map((state?.media?.controls||[]).map(s=>[s.path,s]));
  for(const [path,entry] of canvasMedia){
    const m=states.get(path),player=entry.player;
    if(!m){player.onpause=null;player.pause();player.remove();canvasMedia.delete(path);continue;}
    if(entry.source!==(m.source||'')){
      entry.source=m.source||'';entry.lastTime=-1;
      if(entry.source)player.src=entry.source;else{player.removeAttribute('src');player.load();}
    }
    if(entry.token!==m.token){entry.token=m.token;
      if(player.readyState>=1){
        if(Number.isFinite(player.duration))mediaObservation(entry,'metadata',{duration:player.duration});
        if(Math.abs(player.currentTime-m.time)>0.05)player.currentTime=m.time;
      }
    }
    const playing=m.playing&&!state.inspection&&!$('inspect-toggle').checked;
    if(entry.pending)continue;
    if(playing&&player.paused&&!entry.starting){
      entry.starting=true;
      const token=entry.token;
      player.play().catch(error=>{if(entry.token===token&&error.name!=='AbortError')mediaObservation(entry,'issue',{message:'Browser playback was blocked; use the player controls to start the clip'});}).finally(()=>entry.starting=false);
    }else if(!playing&&!player.paused)player.pause();
  }
}
