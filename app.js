const token = window.CFB_TOKEN;let state={data:{events:[]},picks:[]},selected=null,activeTab=null,view='week',betsOnly=false,week=startWeek(new Date());const form=document.getElementById('pickform');const field=n=>form.elements.namedItem(n);const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const signed=n=>n==null?'—':(n>=0?'+':'')+Number(n);function iso(d){return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`}function startWeek(d){let x=new Date(d.getFullYear(),d.getMonth(),d.getDate(),12);x.setDate(x.getDate()-(x.getDay()+6)%7);return x}function end(){if(activeTab)return iso(new Date(activeTab.end));let d=new Date(week);d.setDate(d.getDate()+6);return iso(d)}function inWeek(r){let e=r.event_id?(state.data.events||[]).find(e=>e.id===r.event_id):r;if(activeTab&&e&&e.week!=null)return e.season===state.data.season&&e.week===activeTab.number&&(e.season_type||2)===activeTab.type;return r.game_date>=iso(week)&&r.game_date<=end()}function notice(s){$('notice').textContent=s;$('notice').style.display='block'}
// The token is minted per server process, so after a restart an open tab gets
// 403 on everything. If the server answers a token-free ping, reload once to
// pick up the new token. The ping and the 30-second guard stop a genuine auth
// failure from turning into a reload loop.
let recovering=false;
async function recoverToken(){
 if(recovering)return true;
 try{
  const ping=await fetch('/api/ping',{cache:'no-store'});
  if(!ping.ok)return false;
  let last=0;try{last=Number(sessionStorage.getItem('cfb-reloaded'))||0}catch(e){}
  if(Date.now()-last<30000)return false;
  try{sessionStorage.setItem('cfb-reloaded',String(Date.now()))}catch(e){}
  recovering=true;
  notice('The tracker restarted. Reloading…');
  location.reload();
  return true;
 }catch(e){return false}
}
async function api(path,body){let r=await fetch('/api/'+path,{method:body?'POST':'GET',headers:{'X-Tracker-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});if(r.status===403&&await recoverToken())return new Promise(()=>{});let d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d}
// Ask only for season data we do not already hold. Two integer comparisons
// replace serialising 2.3MB twice per tick just to spot a change.
async function load(){
 try{
  const next=await api('state?since='+(state.data_revision??-1));
  const changed=next.data_revision!==state.data_revision||next.picks_revision!==state.picks_revision
   ||next.refreshing!==state.refreshing||next.error!==state.error;
  state=Object.assign({},next,{data:('data' in next)?next.data:state.data});
  if(changed)render();
 }catch(e){notice(e.message)}
}
async function refresh(full){try{await api('refresh',{full,week:iso(week),week_end:end()});await load()}catch(e){notice(e.message)}}function currentTab(){let weeks=state.data.weeks||[],now=new Date();return weeks.find(w=>new Date(w.start)<=now&&now<=new Date(w.end))||weeks.find(w=>new Date(w.start)>now)||weeks.at(-1)}
function setTab(w){activeTab=w||null;if(w)week=new Date(w.start);else week=startWeek(new Date())}
// Every week's games are already on the page, so switching renders at once.
// A week still gets one background top-up for fresh odds and weather, but the
// click never waits on it: that sync can mean twenty DraftKings pages.
const toppedUp=new Set();
function topUp(){
 const key=activeTab?activeTab.id:iso(week);
 if(toppedUp.has(key))return;
 toppedUp.add(key);
 api('refresh',{full:false,week:iso(week),week_end:end()}).catch(()=>{});
}
function switchWeek(id){setTab(state.data.weeks.find(w=>w.id===id));clearForm();render();topUp()}
function currentWeek(){setTab(currentTab());clearForm();render();topUp();$('weektabs').querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest',inline:'center'})}
function applyTheme(t){document.documentElement.dataset.theme=t;$('themeToggle').textContent=t==='light'?'🌙 Dark mode':'☀️ Light mode';try{localStorage.setItem('cfb-theme',t)}catch(e){}}
function toggleTheme(){applyTheme(document.documentElement.dataset.theme==='light'?'dark':'light')}
function setView(v){view=v;['week','power','print'].forEach(x=>$('view-'+x).hidden=(x!==v));document.querySelectorAll('.viewtabs [data-view]').forEach(b=>b.setAttribute('aria-selected',b.dataset.view===v))}
document.querySelectorAll('.viewtabs [data-view]').forEach(b=>b.onclick=()=>setView(b.dataset.view));
function setFilter(f){betsOnly=(f==='bets');document.querySelectorAll('.filtertab').forEach(b=>b.setAttribute('aria-selected',b.dataset.filter===f));render()}
document.querySelectorAll('.filtertab').forEach(b=>b.onclick=()=>setFilter(b.dataset.filter));
async function toggleFavorite(id,on){try{await api('favorite',{id,favorite:!on});await load()}catch(e){notice(e.message)}}
function summaryText(rows){let counts={Win:0,Loss:0,Push:0,Pending:0},net=0,risk=0;for(let p of rows){counts[p.result]++;net+=p.profit_units;if(p.result!=='Pending')risk+=p.stake}let decisions=counts.Win+counts.Loss;let pct=decisions?(100*counts.Win/decisions).toFixed(1)+'%':'—';let roi=risk?(100*net/risk).toFixed(1)+'%':'—';return `${counts.Win} W / ${counts.Loss} L / ${counts.Push} Push • ${counts.Pending} pending • Win rate ${pct} • Net ${net>=0?'+':''}${net.toFixed(2)} units • ROI ${roi}`}
function weatherText(e){let w=e.weather;if(e.venue?.indoor)return '<span class="weather">Indoor venue · field conditions sheltered</span>';if(!w?.forecast)return `<span class="weather">${esc(e.weather_status||'Game forecast unavailable')}</span>`;let age=(Date.now()-new Date(w.fetched_at))/3600000;return `<span class="weather">${age>2?'Stale · ':''}<b>${Math.round(w.temperature_2m)}°F</b>, wind ${Math.round(w.wind_speed_10m??0)} mph<br><small>${esc(w.location)} · updated ${esc(new Date(w.fetched_at).toLocaleString())}</small></span>`}

function teamTitle(e,side){let rank=e[side+'_combined'];return `<div class="team-title">${e[side+'_logo']?`<img src="${esc(e[side+'_logo'])}" alt="" loading="lazy">`:''}<div><div class="team-sub">${side==='home'?(e.neutral?'DESIGNATED HOME · NEUTRAL SITE':'HOME'):'AWAY'}${e[side+'_record']?' · '+esc(e[side+'_record']):''}</div><h3>${rank?`<span class="rank" title="Combined CBS / AP / Coaches poll">Poll #${rank}</span> `:''}${esc(e[side])}</h3></div></div>`}
function powerGame(e){return (state.data.power&&state.data.power.games)?state.data.power.games[e.id]:null}
function atsText(a){if(!a||a.wins+a.losses+a.pushes===0)return '';return `${a.wins}-${a.losses}-${a.pushes} ATS`}
function previousGameBlock(e,side){
 const tid=e[side+'_id'],asOf=state.data.power?.as_of||state.today;
 const prior=(state.data.events||[]).filter(g=>g.completed&&g.home_score!=null&&g.away_score!=null&&g.game_date<e.game_date&&(!asOf||g.game_date<asOf)&&(g.home_id===tid||g.away_id===tid)).sort((a,b)=>b.game_date.localeCompare(a.game_date))[0];
 if(!prior)return '';
 const own=prior.home_id===tid?'home':'away',other=own==='home'?'away':'home';
 const scored=prior[own+'_score'],allowed=prior[other+'_score'];
 const result=scored>allowed?'Won':scored<allowed?'Lost':'Tied';
 return `<div class="previous-game"><small>PREVIOUS GAME · ${esc(prior.game_date)}</small><div>vs ${esc(prior[other])} · ${result} ${scored}–${allowed}</div></div>`;
}
function notesBlock(e,side){let p=powerGame(e);if(!p)return '';let notes=(p[side+'_notes']||[]).filter(n=>!n.startsWith('Last result:'));let ats=atsText(p[side+'_ats']);let items=[...(ats?[ats]:[]),...notes];return (items.length?`<div class="notes">${items.map(n=>`<span class="note">${esc(n)}</span>`).join('')}</div>`:'')+previousGameBlock(e,side)}

const half=n=>n==null?'—':(Math.round(Number(n)*2)/2).toFixed(1);
const spreadText=n=>n==null?'—':(Number(n)>0?'+':'')+half(n);
function grades(e,side){let r=(state.data.power?.team_ratings||state.data.power?.ratings||[]).find(r=>r.id===e[side+'_id']);if(r?.ranked===false)return '<div class="grades">Outside FBS ranking pool<small>Not assigned an FBS rank or grade</small></div>';return `<div class="grades">Offense <b>${r?.offense_rank?'#'+r.offense_rank+' · '+r.offense_grade:'Unrated'}</b><br>Defense <b>${r?.defense_rank?'#'+r.defense_rank+' · '+r.defense_grade:'Unrated'}</b>${r?`<small>Out of ${r.ranking_population??state.data.power?.ranking_population??'—'} ${esc(r.ranking_scope||'FBS')} teams · ${r.games} games across recent seasons${r.games<4?' · provisional':''}</small>`:''}</div>`}

function leanLine(e){let p=powerGame(e);let side=p?.lean_side?.toLowerCase();let mark=p?.lean_result==='Win'?' · ✓ RIGHT':p?.lean_result==='Loss'?' · ✗ WRONG':p?.lean_result==='Push'?' · PUSH':'';return `<div class="model-lean">Our lean: <b>${side?esc(e[side])+' '+spreadText(e[side+'_spread'])+mark:'No lean'}</b><br><small>Confidence: ${esc(p?.confidence||'Unavailable')}</small></div>`}
function projectionComparison(e,p){
 const line=p?.lean_home_spread??p?.fair_home_spread;
 if(line==null)return '';
 const label=line===0?'Pick’em':esc(e[line<0?'home':'away'])+' '+spreadText(-Math.abs(line));
 const difference=e.home_spread==null?null:e.home_spread-line;
 const differenceLabel=difference==null?'Unavailable — no market spread':half(Math.abs(difference))+' pts'+(difference===0?' · same as market':' toward '+esc(e[difference>0?'home':'away']));
 return `<div class="projection"><div><b>Our projected line: ${label}</b></div><div>Difference vs market: ${differenceLabel}</div>${p.home_points!=null&&p.away_points!=null?`<div class="projected-score">Projected score: ${esc(e.home)} ${half(p.home_points)} · ${esc(e.away)} ${half(p.away_points)}</div>`:''}</div>`;
}
function powerBlock(e){return leanLine(e)+projectionComparison(e,powerGame(e))}
const money=n=>n==null?'—':(n>=1e6?'$'+(n/1e6).toFixed(1)+'M':'$'+Math.round(n/1e3)+'K');
// Roster cost is the NIL figure but only Power 4 schools report one; athletic
// department expenses stand in so an FCS opponent still shows a real number.
// Both sides are always quoted on whichever measure the model actually used.
const SPEND_FIELDS={roster:['roster_cost','roster cost'],expenses:['athletic_expenses','athletic dept. budget']};
function modelDetail(e,p){
 if(!p||p.lean_source!=='model')return '';
 // Home-spread convention throughout: a positive number favours the home side.
 const toward=n=>n==null?null:(Number(n)===0?'even with the market':half(Math.abs(n))+' pts toward '+esc(Number(n)>0?e.home:e.away));
 let rows=[];
 const raw=toward(p.home_edge_points);
 if(raw)rows.push(`<div>Model line vs market: <b>${raw}</b></div>`);
 // The lean is rounded to a half point, so ignore anything below the smallest
 // real adjustment (1.0 pt) — otherwise rounding shows up as a phantom nudge.
 const nudge=(p.fair_home_spread!=null&&p.lean_home_spread!=null)?p.fair_home_spread-p.lean_home_spread:null;
 if(nudge!=null&&Math.abs(nudge)>=0.5)rows.push(`<div>Situational adjustment: <b>${toward(nudge)}</b><small>Rest, letdown and lookahead notes shown beside each team.</small></div>`);
 const used=toward(p.lean_edge_points);
 if(used)rows.push(`<div>Edge behind the lean: <b>${used}</b><small>Needs 1.0 pt for any lean; 2.0 pts and two games each for Moderate; 4.0 pts and five games each for High.</small></div>`);
 if(p.projected_total!=null){
  const gap=p.total_edge_points;
  const compared=gap==null?'no market total to compare':half(Math.abs(gap))+' pts '+(Number(gap)>=0?'above':'below')+' the market';
  rows.push(`<div>Projected total: <b>${half(p.projected_total)}</b> · ${compared}<small>Context only — this app makes no Over/Under picks.</small></div>`);
 }
 const measure=SPEND_FIELDS[p.spend_measure];
 if(measure){
  const [field,label]=measure;
  const effect=p.spend_margin_shift?toward(p.spend_margin_shift):'no adjustment left — both teams have enough games this season';
  rows.push(`<div>Spending prior: <b>${effect}</b><small>${esc(label)}: ${esc(e.home)} ${money(p.home_spending?.[field])} · ${esc(e.away)} ${money(p.away_spending?.[field])}</small></div>`);
 }
 if(p.home_talent||p.away_talent){
  const talentText=r=>r?`${Number(r.avg_rating).toFixed(2)} avg · #${r.rank}`:'not on the composite';
  // Below a quarter point the half-point display would read "0.0 pts toward" a team.
  const effect=Math.abs(p.talent_margin_shift||0)>=0.25?toward(p.talent_margin_shift):'under half a point';
  rows.push(`<div>Roster talent prior: <b>${effect}</b><small>247Sports average player rating: ${esc(e.home)} ${talentText(p.home_talent)} · ${esc(e.away)} ${talentText(p.away_talent)}</small></div>`);
 }
 if(p.pooled_fcs?.length){
  const who=p.pooled_fcs.map(s=>esc(e[s])).join(' and ');
  rows.push(`<div>FCS opponent: <b>${who}</b><small>Rated as a pooled FCS baseline, not individually. One or two games against FBS teams cannot rate a school on its own.</small></div>`);
 }
 if(p.weather_note)rows.push(`<div class="model-weather">${esc(p.weather_note)}</div>`);
 if(p.confidence_detail)rows.push(`<div><small>${esc(p.confidence_detail)}</small></div>`);
 return rows.length?`<details class="model-detail"><summary>Model detail</summary>${rows.join('')}</details>`:'';
}

function splitsBlock(e){let s=e.home_splits;if(!s)return '';let awayBets=Math.round(100-s.bets),awayMoney=Math.round(100-s.handle);return `<div class="split">Bets: ${esc(e.home)} ${Math.round(s.bets)}% · ${esc(e.away)} ${awayBets}%<br>Money: ${esc(e.home)} ${Math.round(s.handle)}% · ${esc(e.away)} ${awayMoney}%</div>`}
function weatherAlertBlock(e){let p=powerGame(e);return p&&p.weather_alert?`<div class="weather-alert">⚠️ ${esc(p.weather_alert)}</div>`:''}
function trendText(v){if(v==null)return '—';if(v==='new')return 'NEW';if(v===0)return '–';return v>0?`▲${v}`:`▼${Math.abs(v)}`}
function trendClass(v){return (v&&v!=='new'&&v>0)?'win':(v&&v!=='new'&&v<0)?'loss':''}
function renderSpending(){
 let power=state.data.power||{},board=power.spend_board||[],labels=power.spend_labels||{},fit=power.spend_fit||{};
 $('spendnote').textContent=board.length
  ?`${board.length} schools. ${labels.roster||'Roster cost'} is what a program pays its players; ${labels.expenses||'athletic department expenses'} is the whole department and is listed for reference only. `
   +(fit.roster?`Roster cost explains ${Math.round(fit.roster.r_squared*100)}% of the rating spread this refresh (${fit.roster.points_per_doubling} pts per doubling of payroll). It nudges a projection only when both schools report a roster cost and a team has under ${power.spend_fade_games} games this season. Department budgets never move a spread: fitted across FBS and FCS together the line is far too flat to describe those games.`
              :'Not enough overlap with rated teams to fit a relationship, so spending is not affecting any projection.')
  :'School spending has not been loaded yet.';
 $('spendbody').innerHTML=board.map(r=>`<tr><td>${r.spend_rank}</td><td>${esc(r.school)}</td><td>${money(r.roster_cost)}</td><td>${money(r.athletic_expenses)}</td></tr>`).join('')
  ||'<tr><td colspan="4" class="empty">No spending figures available.</td></tr>';
}
function renderTalent(){
 let power=state.data.power||{},board=power.talent_board||[],fit=power.talent_fit;
 $('talentnote').textContent=board.length
  ?`${board.length} rosters from 247Sports' Team Talent Composite, which rates every player on a roster by his recruiting grade. `
   +(fit?`Average player rating explains ${Math.round(fit.r_squared*100)}% of the rating spread this refresh (${fit.slope} rating pts per point of average). It pulls each FBS team ${Math.round((power.talent_max_weight||0)*100)}% of the way toward what its roster implies before it has played, fading to zero at ${power.talent_fade_games} games this season.`
        :'Not enough overlap with rated teams to fit a relationship, so roster talent is not affecting any projection.')
  :'Roster talent has not been loaded yet.';
 $('talentbody').innerHTML=board.map(r=>`<tr><td>${r.rank??'—'}</td><td>${esc(r.team)}</td><td>${r.points==null?'—':Number(r.points).toFixed(2)}</td><td>${r.avg_rating==null?'—':Number(r.avg_rating).toFixed(2)}</td><td>${r.five_star}</td><td>${r.four_star}</td><td>${r.three_star}</td><td>${r.players??'—'}</td></tr>`).join('')
  ||'<tr><td colspan="8" class="empty">No roster talent figures available.</td></tr>';
}
function healthRow(label,value,note){return `<div class="health-row"><span>${esc(label)}</span><b>${value==null||value===''?'—':esc(value)}</b>${note?`<small>${esc(note)}</small>`:''}</div>`}
function renderHealth(){
 let d=state.data||{},power=d.power||{};
 let fit=(power.spend_fit||{}).roster||null;
 let shown=(d.events||[]).filter(inWeek).filter(e=>e.home_combined||e.away_combined);
 let missing=shown.filter(e=>e.home_spread==null);
 let warnings=d.warnings||[];
 $('healthbody').innerHTML=[
  healthRow('Season',d.season),
  healthRow('Feed last refreshed',d.updated_at?new Date(d.updated_at).toLocaleString():null),
  healthRow('Games imported this refresh',d.imported_count),
  healthRow('Betting-splits rows read',d.splits_count,'DraftKings public bet and handle percentages — shown as context, never used by the model.'),
  healthRow('Previous-season games cached',d.history_events_count,'Included in the fit with a 365-day recency half-life.'),
  healthRow('AP poll dated',d.ap_date?new Date(d.ap_date).toLocaleDateString():null),
  healthRow('Model fit as of',power.as_of,'Games on or after this date are excluded from the fit.'),
  healthRow('Ranking comparison pool',power.ranking_population==null?null:power.ranking_population+' '+(power.ranking_scope||'teams')),
  healthRow('Games needed to be rated',power.min_games),
  healthRow('Model weeks reconstructed',power.history_weeks_tracked,'Refit from completed games, so it is complete back to week 1.'),
  healthRow('Poll snapshots archived',d.poll_history_weeks,'Only grows forward: ESPN publishes the current poll only.'),
  healthRow('Spending figures loaded',(power.spend_board||[]).length||null,power.spend_source?'From '+power.spend_source+(power.spend_fetched_at?', fetched '+new Date(power.spend_fetched_at).toLocaleDateString():''):'Not loaded.'),
  healthRow('Roster cost vs rating fit',fit?`${fit.points_per_doubling} pts per doubling · R² ${fit.r_squared} · ${fit.teams} schools`:null,fit?`Refitted every refresh. The prior fades to zero at ${power.spend_fade_games} games and is skipped unless both schools report a roster cost.`:'No fit — spending is not affecting any projection.'),
  healthRow('Roster talent loaded',(power.talent_board||[]).length||null,power.talent_source?'From '+power.talent_source+(power.talent_fetched_at?', fetched '+new Date(power.talent_fetched_at).toLocaleDateString():''):'Not loaded.'),
  healthRow('Roster talent vs rating fit',power.talent_fit?`${power.talent_fit.slope} pts per point of average rating · R² ${power.talent_fit.r_squared} · ${power.talent_fit.teams} schools`:null,power.talent_fit?`Refitted every refresh. The prior fades to zero at ${power.talent_fade_games} games this season.`:'No fit — roster talent is not affecting any projection.'),
  healthRow('Games shown this week',shown.length),
  healthRow('Shown games with no market spread',missing.length,missing.length?missing.map(e=>e.away+' at '+e.home).join(' · '):'Every shown game has a provider line.'),
 ].join('')+(warnings.length?`<div class="health-warnings"><b>Refresh warnings</b>${warnings.map(w=>`<div>${esc(w)}</div>`).join('')}</div>`:'');
}
function renderPower(){
 let power=state.data.power||{};
 $('powerstatus').textContent=(power.status||'Power ratings will appear once this season has completed games.')+(power.history_weeks_tracked?` Retroactive history available for ${power.history_weeks_tracked} week(s) so far.`:'');
 $('trendsince').textContent=power.trend_since||'this week';
 let pollTrend=state.data.poll_trend||{};
 let rows=(power.ratings||[]).slice().sort((a,b)=>a.power_rank-b.power_rank);
 $('powerbody').innerHTML=rows.map(t=>`<tr><td>${t.power_rank}</td><td>${esc(t.team)}</td><td class="${trendClass(t.trend)}">${trendText(t.trend)}</td><td>${half(t.rating)}</td><td>${t.offense_rank?'#'+t.offense_rank:'—'}${t.offense_grade?` (${t.offense_grade})`:''}</td><td>${t.defense_rank?'#'+t.defense_rank:'—'}${t.defense_grade?` (${t.defense_grade})`:''}</td><td>${t.talent?'#'+t.talent.rank:'—'}</td><td>${t.games}</td><td>${t.ats?`${t.ats.wins}-${t.ats.losses}-${t.ats.pushes}`:'—'}</td><td>${t.ap_rank?'#'+t.ap_rank:'—'}</td><td>#${t.combined_rank}</td><td class="${trendClass(pollTrend[t.id])}">${trendText(pollTrend[t.id])}</td></tr>`).join('')||'<tr><td colspan="12" class="empty">No power ratings yet this season.</td></tr>';
 renderSpending();renderTalent();renderHealth();
}
async function quickPick(eventId,side){try{let e=state.data.events.find(e=>e.id===eventId);let existing=state.picks.find(p=>p.event_id===eventId);if(existing?.side===side){notice('This pick is already saved. Use Edit to change its line.');return}if(e.completed){notice('Game is final. Use Edit to record or correct a pick.');return}let key=side.toLowerCase();let spread=e[key+'_spread'];if(spread==null||e[key+'_odds']==null){choose(eventId,side);notice('Enter the missing spread or price to save this pick.');return}let body={game_date:e.game_date,home:e.home,away:e.away,side,spread,odds:e[key+'_odds'],stake:existing?existing.stake:1,home_score:'',away_score:'',notes:existing?existing.notes:'',event_id:eventId,favorite:existing?existing.favorite:0};if(existing)body.id=existing.id;await api('save',body);await load()}catch(err){notice(err.message)}}
function marketLine(e){if(e.home_spread==null)return '<div class="nflspread">No market spread</div>';let side=e.home_spread<=0?'home':'away';return `<div class="nflspread">${esc(e[side])} ${spreadText(e[side+'_spread'])}</div>`}
function matchupCard(e,printing=false){let p=state.picks.find(p=>p.event_id===e.id),address=e.venue?.address||{};let highlighted=printing&&$('highlightPicks')?.checked;
 let sideBlock=side=>`<div class="${side} ${highlighted&&p?.side.toLowerCase()===side?'picked-paper':''}">${teamTitle(e,side)}${grades(e,side)}${side==='home'?`<div class="stadium">${esc(e.venue?.fullName||'Venue unavailable')} · ${esc([address.city,address.state].filter(Boolean).join(', '))}</div>${weatherText(e)}`:''}${notesBlock(e,side)}</div>`;
 let status=e.status&&e.status!=='Scheduled'?' · '+esc(e.status):'';
 let pickClass=side=>{if(p?.side!==side)return '';if(p.result==='Win')return 'chosen pick-won';if(p.result==='Loss')return 'chosen pick-lost';return 'chosen'};
 let pickMark=side=>{if(p?.side!==side)return '';if(p.result==='Win')return ' · ✓ WON';if(p.result==='Loss')return ' · ✗ LOST';if(p.result==='Push')return ' · PUSH';return ' · SAVED'};
 return `<article class="match">${weatherAlertBlock(e)}${sideBlock('home')}<div class="market"><div class="kickoff">${esc(new Date(e.kickoff).toLocaleString([],{weekday:'short',month:'numeric',day:'numeric',hour:'numeric',minute:'2-digit'}))}${status}</div>${printing?marketLine(e):''}<div class="total">O/U ${half(e.total)}</div>${powerBlock(e)}${printing?'':modelDetail(e,powerGame(e))}${printing?'':`<div class="spread-pair">${['Home','Away'].map(side=>`<button class="quickpick ${pickClass(side)}" onclick="quickPick('${e.id}','${side}')" ${e.completed?'disabled':''}>${esc(e[side.toLowerCase()])}<br>${spreadText(e[side.toLowerCase()+'_spread'])}${pickMark(side)}</button>`).join('')}</div><div class="pick-actions"><button class="starbet ${p?.favorite?'on':''}" ${p?'':'disabled'} onclick="${p?`toggleFavorite(${p.id},${!!p.favorite})`:''}">${p?.favorite?'★ BET SAVED':'☆ BET'}</button><button onclick="${p?`edit(${p.id})`:`choose('${e.id}')`}">Edit</button></div>`}<div class="market-source">${esc(e.home_spread==null?(e.odds_status||'No odds supplied by provider'):e.market_source)}${e.market_observed_at?' · '+esc(new Date(e.market_observed_at).toLocaleDateString()):''}</div>${splitsBlock(e)}</div>${sideBlock('away')}</article>`}
function renderPrint(){
 $('printweek').textContent=activeTab?activeTab.label:'This week';
 let games=(state.data.events||[]).filter(inWeek).filter(e=>e.home_combined||e.away_combined);
 $('printboard').innerHTML=games.map(e=>matchupCard(e,true)).join('')||'<div class="empty">No Top 50 matchups this week.</div>';
}
// Update matchup cards in place, keyed by event id, instead of rebuilding the
// list. Unchanged cards keep their DOM node, so an open Model-detail panel and
// the list's scroll position survive a refresh or a saved pick. A card that
// did change is replaced but keeps its panel open if it was. Cards stay direct
// <article class="match"> children so the striping and print grid still match.
const cardCache=new Map();
function renderGames(games){
 const box=$('games');
 if(!games.length){
  cardCache.clear();
  box.innerHTML='<div class="empty">No Top 50 matchups in this week’s imported schedule.</div>';
  return;
 }
 const old=new Map([...box.children].filter(n=>n.dataset.key).map(n=>[n.dataset.key,n]));
 const scroll=box.scrollTop,frag=document.createDocumentFragment();
 for(const e of games){
  const html=matchupCard(e);
  let node=old.get(e.id);
  if(!node||cardCache.get(e.id)!==html){
   const wasOpen=!!node?.querySelector('.model-detail')?.open;
   const t=document.createElement('template');
   t.innerHTML=html;
   const fresh=t.content.firstElementChild;
   fresh.dataset.key=e.id;
   if(wasOpen){const d=fresh.querySelector('.model-detail');if(d)d.open=true}
   node=fresh;
   cardCache.set(e.id,html);
  }
  old.delete(e.id);
  frag.appendChild(node);
 }
 for(const [key,node] of old){cardCache.delete(key);node.remove()}
 box.replaceChildren(frag);
 box.scrollTop=scroll;
}
// Edge points scale from 1.0 (the minimum for any lean at all) to 4.0 (this
// model's unreached High threshold). We map that onto a 1-10 display rating
// so a Moderate-confidence game near the 2.0pt threshold reads as ~5/10 and
// one near the top of the observed range reads closer to 10/10. It is a
// relabeling of the existing edge, not a new signal.
function confidenceRating(e){let edge=powerGame(e)?.lean_edge_points;if(edge==null)return null;return Math.max(1,Math.min(10,Math.round(edge*2.5)))}
// "Moderate" (this model's ceiling label) needs 2+ games played by both
// teams, which most of the slate won't have until well into the season — a
// strict Moderate-only filter left this section empty most weeks. Instead we
// rank every game in the week that has any lean at all (|edge| >= 1pt, the
// model's own floor for issuing one) by edge size, and cap it at the top 5,
// so "our best picks this week" always means the best of what's actually on
// the board rather than an absolute bar the early season rarely clears.
function renderTopPicks(games){
 let card=$('toppicks-card'),box=$('toppicks');
 let picks=games.filter(e=>!e.completed&&powerGame(e)?.lean_side)
  .sort((a,b)=>Math.abs(powerGame(b).lean_edge_points||0)-Math.abs(powerGame(a).lean_edge_points||0))
  .slice(0,5);
 if(!picks.length){card.hidden=true;box.innerHTML='';return}
 card.hidden=false;
 box.innerHTML=picks.map(e=>`<div class="toppick"><div class="rating-badge">Confidence <b>${confidenceRating(e)}</b>/10</div>${matchupCard(e)}</div>`).join('');
}
function render(){
 let d=state.data||{},firstWeek=!activeTab;if(!activeTab&&(d.weeks||[]).length)setTab(currentTab());
 $('weektitle').textContent=(activeTab?activeTab.label+' · ':'')+(activeTab?.detail||(iso(week)+' — '+end()));$('matchtitle').textContent=(activeTab?activeTab.label:'This week')+' matchups';
 $('weektabs').innerHTML=(d.weeks||[]).map(w=>`<button role="tab" aria-selected="${activeTab?.id===w.id}" data-week="${esc(w.id)}">${esc(w.label)}${currentTab()?.id===w.id?'<small>CURRENT WEEK</small>':''}</button>`).join('');$('weektabs').querySelectorAll('[data-week]').forEach(b=>b.onclick=()=>switchWeek(b.dataset.week));
 if(firstWeek&&activeTab)requestAnimationFrame(()=>$('weektabs').querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest',inline:'center'}));
 $('source').textContent=(state.refreshing?'Refreshing… ':state.error?'Refresh failed; using saved data. '+state.error+' ':'')+`Season ${d.season||'—'} · ${(d.top50||[]).length} combined teams · Updated ${d.updated_at||'not yet'}`+(d.warnings?.length?' · '+d.warnings.join(' | '):'');
 $('roster').innerHTML=(d.top50||[]).map(t=>`<div><b class="rank">${t.rank}.</b> ${esc(t.team)}<br><small>CBS ${t.cbs||'—'} · AP ${t.ap||'—'} · Coaches ${t.coaches||'—'}</small></div>`).join('');
 let games=(d.events||[]).filter(inWeek).filter(e=>e.home_combined||e.away_combined);
 renderGames(games);
 renderTopPicks(games);
 let allPicks=betsOnly?state.picks.filter(p=>p.favorite):state.picks;
 let picks=allPicks.filter(inWeek),w=picks.filter(p=>p.result==='Win').length,l=picks.filter(p=>p.result==='Loss').length,push=picks.filter(p=>p.result==='Push').length,pending=picks.filter(p=>p.result==='Pending').length,net=picks.reduce((s,p)=>s+p.profit_units,0);
 $('metrics').innerHTML=`<div class="metric"><strong>${w}–${l}–${push}</strong><small>Wins · losses · pushes</small></div><div class="metric"><strong>${pending}</strong><small>Pending picks</small></div><div class="metric"><strong>${w+l?(100*w/(w+l)).toFixed(1)+'%':'—'}</strong><small>ATS win rate (excludes pushes)</small></div><div class="metric"><strong>${net>=0?'+':''}${net.toFixed(2)}</strong><small>Net units</small></div>`;
 $('picks').innerHTML=picks.map(p=>`<tr class="${p.favorite?'favorite':''}"><td><button class="starbtn" data-fav="${p.id}" data-on="${p.favorite?1:0}" title="${p.favorite?'Remove from my bets':'Mark as a real bet'}">${p.favorite?'★':'☆'}</button></td><td>${esc(p.game_date)}</td><td>${esc(p.away)} @ ${esc(p.home)}</td><td><b>${esc(p.side==='Home'?p.home:p.away)} ${signed(p.spread)}</b></td><td>${signed(p.odds)} · ${p.stake}</td><td>${p.result==='Pending'?'—':p.away_score+'–'+p.home_score}</td><td class="${p.result==='Win'?'win':p.result==='Loss'?'loss':''}">${p.result}</td><td>${p.result==='Pending'?'—':p.profit_units.toFixed(2)}</td><td><button data-pick="${p.id}">Edit</button></td></tr>`).join('')||`<tr><td colspan="9" class="empty">${betsOnly?'No bets marked yet — click the star beside a saved pick.':'Your saved picks will appear here.'}</td></tr>`;
 $('picks').querySelectorAll('[data-pick]').forEach(b=>b.onclick=()=>edit(Number(b.dataset.pick)));
 $('picks').querySelectorAll('[data-fav]').forEach(b=>b.onclick=()=>toggleFavorite(Number(b.dataset.fav),b.dataset.on==='1'));
 $('allstats').textContent=(betsOnly?'All time (my bets only): ':'All time: ')+summaryText(allPicks);
 renderPower();renderPrint();
}
function clearForm(){$('editor').hidden=true;form.reset();field('id').value='';field('event_id').value='';field('game_date').value=iso(week);selected=null;$('formtitle').textContent='Record your pick';$('pickcontext').textContent='Choose a matchup above to fill in its available line, or enter a pick here.'}
function choose(id,side='Home'){let prior=state.picks.find(p=>p.event_id===id);if(prior)return edit(prior.id);clearForm();selected=state.data.events.find(e=>e.id===id);for(let k of ['game_date','home','away','home_score','away_score'])field(k).value=selected[k]??'';field('event_id').value=id;field('side').value=side;sideChanged();$('editor').hidden=false;$('pickcontext').textContent=`${selected.market_source||'Line unavailable — enter your own'} · Captured ${selected.market_observed_at}. Final scores update on refresh.`;$('editor').scrollIntoView({behavior:'smooth',block:'center'})}
function sideChanged(){if(!selected||field('id').value)return;let side=field('side').value.toLowerCase();field('spread').value=selected[side+'_spread']??'';field('odds').value=selected[side+'_odds']??''}
function edit(id){clearForm();let p=state.picks.find(p=>p.id===id);for(let e of form.elements)if(e.name&&Object.hasOwn(p,e.name)){if(e.type==='checkbox')e.checked=!!p[e.name];else e.value=p[e.name]??''}$('editor').hidden=false;$('formtitle').textContent='Edit saved pick #'+id;$('pickcontext').textContent='Editing your recorded pick. Automatic market refreshes preserve this spread and price.';$('editor').scrollIntoView({behavior:'smooth',block:'center'})}
form.onsubmit=async e=>{e.preventDefault();try{await api('save',Object.fromEntries(new FormData(form)));clearForm();notice('Pick saved. Your original line is recorded.');await load()}catch(e){notice(e.message)}};
let savedTheme='dark';try{savedTheme=localStorage.getItem('cfb-theme')||'dark'}catch(e){}applyTheme(savedTheme);
clearForm();load();setInterval(load,5000);setInterval(()=>refresh(false),900000);
