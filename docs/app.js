const byId = id => document.getElementById(id);
const sites = [
  {id:'A',name:'Western terrace',x:28,y:39,solar:.94,wind:.58,slope:.8,land:.83,grid:.72},
  {id:'B',name:'Northern ridge',x:59,y:23,solar:.71,wind:.96,slope:.63,land:.8,grid:.78},
  {id:'C',name:'Eastern plain',x:72,y:65,solar:.8,wind:.67,slope:.9,land:.68,grid:.62}
];
const hazards = [
  ['Dumping review','New ground disturbance','Check site permits and request dated imagery of the disturbed patch.'],
  ['Landfill methane','Plume retrieval','Request a methane-specific measurement and a background reading.'],
  ['Airborne plume','Visible plume','Compare winds and request a calibrated air sample.'],
  ['Coastal slick','Radar anomaly','Review wind and sea state before requesting a water sample.'],
  ['River discharge','Colour change','Compare upstream and downstream imagery and request paired samples.'],
  ['Tailings dam','Displacement trend','Refer the simulated trend to a geotechnical reviewer for instrument checks.'],
  ['Waste slope','Possible collapse','Review elevation changes and request an engineering inspection.']
];
let tab = 'siting', selected = 'A';
const titles = {siting:'Candidate sites',build:'Construction observations',watch:'Environmental cases'};
function records() {
  if (tab==='siting') {
    const solar=byId('mode').value==='Solar';
    return sites.map(s=>{
      const resource=solar?s.solar:s.wind;
      const score=Math.round(100*((solar?.4:.45)*resource+(solar?.25:.15)*s.slope+.2*s.land+(solar?.15:.2)*s.grid));
      return {...s,score,value:score+' / 100',measure:byId('mode').value+' suitability',detail:'Weighted screening score',review:'Survey decision',finding:'Compare land eligibility and likely connection distance before commissioning a survey.',
        source:'Illustrative normalized inputs · Resource '+resource+' · Slope benefit '+s.slope+' · Eligible land '+s.land+' · Grid proximity '+s.grid+'. Weights in that order: '+(solar?'40 / 25 / 20 / 15%.':'45 / 15 / 20 / 20%.')};
    }).sort((a,b)=>b.score-a.score);
  }
  if (tab==='build') return [{id:'K',name:'Khavda pilot',x:46,y:43,value:'18.4 ha',measure:'Newly visible infrastructure',detail:'82% common valid coverage',review:'Milestone review',finding:'Inspect the paired footprint before accepting the visible construction milestone.',source:'Illustrative March 2024 and March 2025 comparison. Only clear pixels on both dates count. The review threshold is 70%.'}];
  return hazards.map(([name,measure,finding],i)=>({id:String(i+1),name,measure,finding,x:[15,37,62,82,25,52,73][i],y:[32,23,33,42,66,75,64][i],value:'Review',detail:'Simulated orbital observation',review:'Next evidence request',source:'Simulated response chain: satellite flag → HAPS watch → drone or field evidence. Analyst confirmation is pending.'}));
}
function selector(record, map) {
  const button=document.createElement('button');
  button.className=map?'pin':'row';
  button.setAttribute('aria-pressed',String(record.id===selected));
  button.setAttribute('aria-label','Select '+record.name);
  if(map){
    button.style.left=record.x+'%';button.style.top=record.y+'%';button.textContent=record.id;
  }else{
    for(const [text,cls] of [[record.id,'code'],[record.name,'name'],[record.value,'result']]){
      const span=document.createElement('span');span.className=cls;span.textContent=text;button.append(span);
    }
  }
  button.onclick=()=>{selected=record.id;render();const group=byId(map?'pins':'rows');group.querySelector('[aria-pressed=true]').focus();};
  return button;
}
function render(){
  const list=records(), item=list.find(s=>s.id===selected)||list[0];selected=item.id;
  document.querySelectorAll('[data-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tab===tab)));
  byId('listtitle').textContent=titles[tab];byId('modewrap').hidden=tab!=='siting';
  byId('kind').textContent={siting:'SITE DOSSIER',build:'CONSTRUCTION DOSSIER',watch:'SIMULATED CASE'}[tab];
  byId('site').textContent=item.name;
  for(const key of ['value','measure','detail','review','finding','source'])byId(key).textContent=item[key];
  byId('pins').replaceChildren(...list.map(s=>selector(s,true)));
  byId('rows').replaceChildren(...list.map(s=>selector(s,false)));
  byId('evidence').open=false;
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;selected=null;render();});
byId('mode').onchange=()=>{selected=null;render();};
byId('export').onclick=()=>{
  const item=records().find(s=>s.id===selected);
  const brief=['# Kutch portfolio brief','Illustrative pilot · '+titles[tab],'## '+item.name,item.measure+' — '+item.value,item.detail,item.finding,item.source].join('\n\n');
  const url=URL.createObjectURL(new Blob([brief],{type:'text/markdown'}));
  const link=document.createElement('a');link.href=url;link.download='orbitworks-'+tab+'-'+item.id+'.md';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
render();
