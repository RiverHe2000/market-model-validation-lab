"""A small offline explorer for aggregate findings, with no model recalibration."""

from __future__ import annotations

import json
from pathlib import Path


SCRIPT = r"""
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
"""


def write_explorer(output: Path, document, market: dict, options: dict) -> None:
    # Explicit aggregate allowlist: pair_exclusions contains individual quote IDs
    # and remains local even if future schemas add more record-level diagnostics.
    public = {
        "market": {"annual": market["annual"], "events": [
            {key: event[key] for key in ("event_id", "anchor_date", "signed_hpl_eur", "currency_hpl_eur", "models")}
            for event in market["events"]]},
        "options": {key: options[key] for key in ("population", "matched_rate", "error_slices")},
    }
    payload = json.dumps(public, allow_nan=False).replace("<", "\\u003c")
    body = """<nav class='top-nav'><a href='index.html'>← 项目首页</a><a href='#market'>市场风险</a><a href='#options'>期权定价</a></nav>
<p class='eyebrow'>Explore the evidence · 事后描述性分析</p><h1>把结论拆开看。</h1>
<p class='intro'>切换年份、模型和样本口径，查看平均结果背后的差异。所有数据来自已经验证的固定预测；页面不重新拟合模型。</p>
<section id='market' class='panel'><p class='eyebrow'>01 · 时间与尾部风险</p><h2>长期平均，是否掩盖了某些年份？</h2>
<div class='filters'><label>观察年份<select id='year'></select></label><label>图中模型<select id='model'></select></label></div>
<div class='kpis' aria-live='polite'><div><small>实际超越 / 观察日数</small><strong id='hits'></strong></div><div><small>99% VaR 理论超越次数</small><strong id='expected'></strong></div><div><small>该年最大单日超出 VaR</small><strong id='gap'></strong></div></div>
<p id='year-note' class='muted'></p><div class='table-scroll'><table id='annual-table'></table></div>
<details><summary>查看所选模型的完整年度分布</summary><p class='muted'>深色：评估期；浅色：开发期。竖线是 1% 参考超越率，并非每年必须刚好达到的目标。</p><div id='annual-bars'></div></details>
<p class='muted'>“最大超出 VaR”是当天实际损失与风险预测的差额，不等同于资本要求或可避免损失。FZ0 越低越好，但不能代替覆盖率检验。</p>
<a href='market-risk/report.html'>阅读全文与原始统计检验 →</a></section>
<section class='panel'><p class='eyebrow'>02 · 事件与信息边界</p><h2>冲击发生前后，模型知道什么？</h2>
<div class='filters'><label>事件窗口<select id='event'></select></label></div><div class='event-result'><small id='event-direction'></small><strong id='event-value'></strong></div><p id='event-note' class='muted'></p>
<div class='table-scroll'><table id='event-table'></table></div><details><summary>查看五币种损益贡献</summary><table id='currency-table'></table></details>
<p class='muted'>瑞郎事件保留预先指定的日期；各压力年最大损失日是事后定位的解释案例。前后20个已观察交易日的对照不代表因果效应。</p></section>
<section id='options' class='panel'><p class='eyebrow'>03 · 相同报价的情景比较</p><h2>改变利率假设，误差变化有多大？</h2>
<div class='filters'><label>研究区间<select id='split'></select></label><label>基准报价组<select id='cohort'></select></label><label>汇总权重<select id='weight'></select></label></div>
<p id='pair-note' class='muted' aria-live='polite'></p><div class='table-scroll'><table id='rate-table'></table></div>
<p>每个情景都使用同一批报价，并用原来的训练行权价重新估计远期和共同波动率。因此这里显示的是完整重校准后的情景差异，不能当作单独的 Rho 或实际加息的因果影响。</p>
<h3>共同波动率在哪些行权价区域失效？</h3><div class='filters'><label>期权类型<select id='kind'></select></label></div><div class='table-scroll'><table id='slice-table'></table></div>
<p class='muted'>误差单位是指数点；有符号误差 = 模型价格 − 报价中点。等日期、等组权重减少报价数量分布的影响，但不会让重复观察变成独立样本。行权价区域表使用该基准组的全部留出报价；上方情景表只使用三个情景共有的报价。</p>
<a href='options/report.html'>阅读全文、报价限制与独立验证 →</a></section>
<aside class='note'>这些诊断在第一轮结果之后增加，用于解释现象。没有新增显著性结论，也没有调整模型参数来改善已看过的评估结果。</aside>"""
    script = f"<script id='evidence-data' type='application/json'>{payload}</script><script src='assets/explorer.js'></script>"
    (output / "assets").mkdir(exist_ok=True)
    (output / "assets/explorer.js").write_text(SCRIPT, encoding="utf-8")
    (output / "evidence.html").write_text(document("模型验证 · 交互式证据", body, script, lang="zh-CN"), encoding="utf-8")
