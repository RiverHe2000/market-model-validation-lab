
const data=JSON.parse(document.getElementById('evidence-data').textContent);
const $=id=>document.getElementById(id);
const names={historical:'历史模拟',ewma_gaussian:'EWMA 正态',ewma_fhs:'EWMA 过滤历史模拟'};
const statusNames={ALL_BASE_STATUSES:'所有基准组',PARITY_COMPATIBLE_DAILY_PROXY:'基准平价兼容组',EXPLORATORY_INCONSISTENT_QUOTES:'基准报价不一致组'};
const number=(x,d=0)=>x==null?'—':Number(x).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=x=>x==null?'—':number(x*100,2)+'%';
const signed=(x,d=0)=>(x>0?'+':'')+number(x,d);
function options(id,rows){for(const [value,label] of rows){let o=document.createElement('option');o.value=value;o.textContent=label;$(id).append(o);}}
function table(id,headers,rows){const target=$(id);target.replaceChildren();let head=document.createElement('thead'),tr=document.createElement('tr');for(const title of headers){let th=document.createElement('th');th.textContent=title;th.scope='col';tr.append(th);}head.append(tr);target.append(head);let body=document.createElement('tbody');for(const row of rows){let line=document.createElement('tr');for(const value of row){let td=document.createElement('td');td.textContent=String(value);line.append(td);}body.append(line);}target.append(body);}
function metric(id,value){$(id).textContent=value;}
const years=[...new Set(data.market.annual.map(x=>x.year))].sort((a,b)=>a-b);
options('year',years.map(y=>[y,y+' · '+(y<2010?'开发期':'评估期')]));$('year').value=years.includes(2020)?2020:years.at(-1);
options('model',Object.entries(names));$('model').value='ewma_gaussian';
function annual(){let rows=data.market.annual.filter(x=>x.year==$('year').value),r=rows.find(x=>x.model==$('model').value);if(!r)return;
metric('hits',number(r.exceptions_99)+' / '+number(r.n));metric('expected',number(r.expected_exceptions_99,2));metric('gap','€'+number(r.max_excess_99_eur));
metric('year-note',r.tail_count_975+' 次 97.5% 尾部观察；分年数据仅用于描述，未做新增显著性检验或重新选择模型。');
table('annual-table',['方法','99% 超越率','平均 VaR (EUR)','平均 ES (EUR)','最大超出 VaR (EUR)','联合评分 FZ0 ↓'],rows.map(x=>[names[x.model],pct(x.exception_rate_99),number(x.mean_var_99_eur),number(x.mean_es_975_eur),number(x.max_excess_99_eur),number(x.fz0_mean,4)]));
let historical=data.market.annual.filter(x=>x.model==$('model').value);const box=$('annual-bars');box.replaceChildren();let max=Math.max(1,...historical.map(x=>x.exception_rate_99*100));for(const x of historical){let line=document.createElement('div');line.className='bar-row';let year=document.createElement('span');year.textContent=x.year;let track=document.createElement('div');track.className='bar-track';let bar=document.createElement('div');bar.className='bar';bar.style.width=(x.exception_rate_99*100/max*100)+'%';if(x.year<2010)bar.classList.add('development');let reference=document.createElement('span');reference.className='reference';reference.style.left=(100/max)+'%';track.append(bar,reference);let value=document.createElement('span');value.textContent=pct(x.exception_rate_99);line.append(year,track,value);box.append(line);}}
options('event',data.market.events.map(e=>[e.event_id,e.event_id==='chf_floor_2015'?'2015-01-15 · 瑞郎事件':e.anchor_date+' · 压力年最大损失日']));
function event(){const e=data.market.events.find(x=>x.event_id==$('event').value);if(!e)return;metric('event-value',signed(e.signed_hpl_eur)+' EUR');metric('event-direction',e.signed_hpl_eur>=0?'当日组合收益':'当日组合损失');metric('event-note',e.anchor_date+'；正值代表收益。次日风险已观察到事件冲击，不能当作事件前的预测。');
table('currency-table',['币种','当日损益贡献 (EUR)'],Object.entries(e.currency_hpl_eur).map(([k,v])=>[k,signed(v)]));
table('event-table',['方法','事件前信息日','当日 VaR','次日 VaR','次日 / 当日','此前20日均值','随后20日均值'],e.models.map(x=>[names[x.model],x.anchor_as_of,'€'+number(x.anchor_var_99_eur),'€'+number(x.next_var_99_eur),number(x.next_to_anchor_var_ratio,2)+'×','€'+number(x.pre_mean_var_99_eur),'€'+number(x.post_mean_var_99_eur)]));}
options('split',[['temporal_test','9–12 月评估'],['development','7–8 月开发']]);
options('cohort',Object.entries(statusNames));$('cohort').value='PARITY_COMPATIBLE_DAILY_PROXY';
options('weight',[['','按报价平均'],['equal_date_','每个日期等权'],['equal_group_','每个日期/到期日等权']]);
options('kind',[['all','Call 与 Put'],['call','仅 Call'],['put','仅 Put']]);
function paired(){const split=$('split').value,status=$('cohort').value,weight=$('weight').value;let rows=data.options.matched_rate.filter(x=>x.split===split&&x.base_group_status===status);table('rate-table',['折现利率假设','固定报价数','基准 MAE','情景 MAE','MAE 变化','价差覆盖率变化'],rows.map(x=>[(x.rate_shift>0?'+':'')+number(x.rate_shift*10000)+' bp',number(x.common_quotes),number(x[weight+'base_mae_points'],2),number(x[weight+'shift_mae_points'],2),signed(x[weight+'delta_mae_points'],2),signed(x[weight+'delta_coverage_pp'],2)+' 个百分点']));
metric('pair-note',rows.length?number(rows[0].common_quotes)+' 条相同报价 · '+rows[0].dates+' 个日期 · '+number(rows[0].common_groups)+' 个日期/到期日组合。分层固定在基准状态。':'该组无共同样本。');
let slices=data.options.error_slices.filter(x=>x.split===split&&x.base_group_status===status&&x.call_put===$('kind').value);table('slice-table',['行权价 / 现货价','报价数','覆盖率','平均绝对误差','有符号平均误差'],slices.map(x=>[x.moneyness_band==='all'?'全部范围':x.moneyness_band,number(x.quotes),pct(x[weight+'coverage']),number(x[weight+'mae_points'],2),signed(x[weight+'mean_error_points'],2)]));}
$('year').onchange=annual;$('model').onchange=annual;$('event').onchange=event;for(const id of ['split','cohort','weight','kind'])$(id).onchange=paired;
annual();event();paired();
