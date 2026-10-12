// Execute the real chart code and verify its output callbacks across HTMX swaps.
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const assert = require('node:assert/strict');
const code = readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
const root = {lang:'en', dataset:{showCents:'true'}};
const handlers = {}, options = {}, chartHandlers = {};
const nodes = Object.fromEntries(['history-chart', 'assets-chart', 'liquidity-chart', 'movement-chart'].map(id=>[id,{id}]));
nodes['chart-data'] = {textContent:JSON.stringify({years:['2026'],series:[],assets:[{value:1234.56}],liquidity:[{value:-1234.56}]})};
nodes['movement-data'] = {textContent:JSON.stringify({labels:['Gain'],values:[-1234.56],detail_ids:['movement-investments']})};
let focused = false, scrolled = false;
nodes['movement-investments'] = {open:false,querySelector:()=>({focus:()=>focused=true}),scrollIntoView:()=>scrolled=true};
const echarts = {init:node=>({setOption:option=>options[node.id]=option,on:(event,fn)=>chartHandlers[node.id+event]=fn,dispose(){}})};
runInNewContext(code, {
  Intl, document:{documentElement:root,getElementById:id=>nodes[id],addEventListener:(event,fn)=>handlers[event]=fn},
  window:{echarts,addEventListener(){}}, echarts,
  getComputedStyle:()=>({getPropertyValue:()=> '#ffffff'})
});
for (const lang of ['en','nl','en']) {
  root.lang = lang;
  for (const cents of ['true','false']) {
    root.dataset.showCents = cents;
    handlers['htmx:afterSwap']();
    const number = lang==='nl' ? (cents==='true'?'1.234,56':'1.235') : (cents==='true'?'1,234.56':'1,235');
    assert.ok(options['history-chart'].tooltip.valueFormatter(1234.56).includes(number));
    assert.equal(options['liquidity-chart'].xAxis.axisLabel.formatter(-1234.56), lang==='nl'?'-1.234,56':'-1,234.56');
    assert.equal(options['assets-chart'].series[0].emphasis.label.formatter({percent:12.34}), lang==='nl'?'12,34%':'12.34%');
    assert.ok(options['history-chart'].yAxis.axisLabel.formatter(1234).includes(lang==='nl'?'1,2':'1.2'));
  }
}
delete nodes['chart-data'];
handlers['htmx:afterSwap']();
for (const lang of ['en','nl']) {
  root.lang = lang;
  handlers['htmx:afterSwap']();
  const tooltip = options['movement-chart'].tooltip.formatter([{dataIndex:0}]);
  assert.ok(tooltip.includes('-'));
  assert.ok(tooltip.includes(lang==='nl'?'1.235':'1,235'));
}
chartHandlers['movement-chartclick']({dataIndex:0});
assert.ok(nodes['movement-investments'].open && focused && scrolled);
chartHandlers['movement-chartclick']({dataIndex:99});
console.log('Chart locale callbacks and HTMX redraw checks passed.');
// Decimal percentages arrive as strings; chart values convert only for plotting.
nodes['asset-mix-chart'] = {id:'asset-mix-chart'};
nodes['chart-data'] = {textContent:JSON.stringify({years:['2026'],series:[],assets:[],liquidity:[],mix:{
  dates:['2026-08-11'],carried_label:'Carried forward',unavailable_label:'Unavailable',missing_label:'Missing',missing:[['Example missing']],
  series:[{name:'Cash',data:[{value:'12.34',amount:123456,carried_dates:['2024-12-17']}]}]
}})};
for (const lang of ['en','nl']) {
  root.lang = lang;
  for (const cents of ['true','false']) {
    root.dataset.showCents = cents;
    handlers['htmx:afterSwap']();
    const mix = options['asset-mix-chart'];
    assert.equal(mix.series[0].data[0].value, 12.34);
    assert.equal(mix.yAxis.max, 100);
    const tip = mix.tooltip.formatter([{dataIndex:0}]);
    assert.ok(tip.includes(lang==='nl'?'12,34%':'12.34%'));
    assert.ok(tip.includes(lang==='nl'?(cents==='true'?'1.234,56':'1.235'):(cents==='true'?'1,234.56':'1,235')));
    assert.ok(tip.includes(lang==='nl'?'11-8-2026':'8/11/2026'));
    assert.ok(tip.includes(lang==='nl'?'17-12-2024':'12/17/2024'));
    assert.ok(tip.includes('Carried forward') && tip.includes('Example missing'));
  }
}
const empty = JSON.parse(nodes['chart-data'].textContent);
empty.mix.series[0].data[0].value = null;
nodes['chart-data'].textContent = JSON.stringify(empty);
handlers['htmx:afterSwap']();
assert.equal(options['asset-mix-chart'].series[0].data[0].value, null);
assert.ok(options['asset-mix-chart'].tooltip.formatter([{dataIndex:0}]).includes('Unavailable'));
// Account history uses a true time axis, gross cents, and gaps for unknown deposits.
delete nodes['chart-data'];
nodes['investment-chart'] = {id:'investment-chart'};
nodes['investment-data'] = {textContent:JSON.stringify({dates:['2026-01-03','2026-02-19','2026-04-01','2026-07-11'],unknown_label:'Unknown',series:[
  {name:'Value',data:[11800000,10800000,10800001,1800001]},
  {name:'Deposits',data:[10000000,9000000,null,0]},
  {name:'Result',data:[1800000,1800000,null,1800001]}
]})};
for (const lang of ['en','nl']) {
  root.lang = lang;
  for (const cents of ['true','false']) {
    root.dataset.showCents = cents;
    handlers['htmx:afterSwap']();
    const chart = options['investment-chart'];
    assert.equal(chart.xAxis.type,'time');
    assert.equal(chart.series[2].data[0][1],18000);
    assert.equal(chart.series[2].data[1][1],18000);
    assert.equal(chart.series[2].data[2][1],null);
    assert.equal(chart.series[1].data[3][1],0);
    assert.equal(chart.series[2].connectNulls,false);
    assert.equal(chart.series[2].smooth,false);
    const tip = chart.tooltip.formatter([{dataIndex:3}]);
    assert.ok(tip.includes(lang==='nl'?(cents==='true'?'18.000,01':'18.000'):(cents==='true'?'18,000.01':'18,000')));
    assert.ok(tip.includes(lang==='nl'?'11-7-2026':'7/11/2026'));
    assert.ok(chart.tooltip.formatter([{dataIndex:2}]).includes('Unknown'));
    const intervals = chart.series[0].data.map(p=>p[0]);
    assert.notEqual(intervals[1]-intervals[0],intervals[3]-intervals[2]);
  }
}
console.log('Investment history dates, gaps and locale checks passed.');
