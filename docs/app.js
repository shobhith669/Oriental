const byId = id => document.getElementById(id);
const connected = document.documentElement.dataset.mode === 'connected';
const titles = {siting:'Candidate sites', build:'Construction observations', watch:'Environmental cases'};
let catalog, actions, tab = 'siting', selected = 'A';
let generation = 0, version = 0, historyRows = [];
function records() {
  return tab === 'siting' ? catalog.siting[byId('mode').value] : catalog[tab];
}
function recordKey() {
  return tab === 'siting' ? [tab, byId('mode').value, selected].join('-') : [tab, selected].join('-');
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
  byId('masks').hidden = tab !== 'build';
  if (connected) loadHistory();
}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>{tab=b.dataset.tab;selected=null;render();});
byId('mode').onchange=()=>{selected=null;render();};
byId('export').onclick=()=>{
  const item=records().find(s=>s.id===selected);
  const brief=['# Kutch portfolio brief','Illustrative pilot · '+titles[tab],'## '+item.name,item.measure+' — '+item.value,item.detail,item.finding,item.source,...historyRows.map(r => r.saved_at+' UTC · '+r.action)].join('\n\n');
  const url=URL.createObjectURL(new Blob([brief],{type:'text/markdown'}));
  const link=document.createElement('a');link.href=url;link.download='orbitworks-'+tab+'-'+item.id+'.md';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
};
function setActive(active) {
  byId('export').disabled = !active;
  byId('mode').disabled = !active;
  document.querySelectorAll('[data-tab]').forEach(button => button.disabled = !active);
}

async function loadHistory(message = '') {
  const token = ++generation;
  const key = recordKey();
  historyRows = [];
  byId('export').disabled = true;
  byId('decisions').hidden = false;
  byId('save').disabled = true;
  byId('history').replaceChildren();
  byId('decision').replaceChildren(...actions[tab].map(action => new Option(action, action)));
  byId('decision-status').textContent = 'Loading decisions…';
  try {
    const response = await fetch('api/reviews/' + key, {cache:'no-store'});
    if (!response.ok) throw new Error();
    const rows = await response.json();
    if (token !== generation) return;
    historyRows = rows;
    version = rows[0]?.version ?? 0;
    byId('history').replaceChildren(...rows.map(row => {
      const item = document.createElement('li');
      item.textContent = row.action + ' · ' + row.saved_at + ' UTC';
      return item;
    }));
    byId('decision-status').textContent = message || (rows.length ? '' : 'No decisions recorded.');
    byId('save').disabled = false;
    byId('export').disabled = false;
  } catch {
    if (token === generation) byId('decision-status').textContent = 'Could not load decisions. Select the record again to retry.';
  }
}

byId('decision-form').onsubmit = async event => {
  event.preventDefault();
  if (byId('save').disabled) return;
  const token = generation;
  byId('save').disabled = true;
  byId('export').disabled = true;
  byId('decision-status').textContent = 'Saving…';
  try {
    const response = await fetch('api/reviews/' + recordKey(), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:byId('decision').value, version})
    });
    if (token !== generation) return;
    if (response.status === 409) {
      await loadHistory('Another reviewer saved a decision. Check the latest entry before saving.');
    } else if (response.ok) {
      await loadHistory('Decision saved.');
    } else {
      throw new Error();
    }
  } catch {
    if (token === generation) await loadHistory('Save could not be confirmed. Check the log before retrying.');
  }
};

byId('scene-year').onchange = event => {
  const year = event.target.value;
  byId('mask-image').src = 'assets/mask-' + year + '.png';
  byId('mask-image').alt = 'Simulated classified footprint for March ' + year;
};

async function start() {
  setActive(false);
  try {
    const response = await fetch(connected ? 'api/portfolio' : 'pilot.json');
    if (!response.ok) throw new Error();
    const payload = await response.json();
    catalog = connected ? payload.portfolio : payload;
    actions = payload.actions;
    byId('load-status').textContent = connected ? '' : 'Read-only preview · Run the Python app to save decisions.';
    setActive(true);
    render();
  } catch {
    byId('load-status').textContent = 'Could not load the portfolio. Reload to retry.';
  }
}
start();
