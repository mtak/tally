// Execute the real chart code and verify its output callbacks across HTMX swaps.
const {readFileSync} = require('node:fs');
const {runInNewContext} = require('node:vm');
const assert = require('node:assert/strict');
const code = readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
const root = {lang:'en', dataset:{showCents:'true'}};
const handlers = {}, options = {};
const nodes = Object.fromEntries(['history-chart', 'assets-chart', 'liquidity-chart', 'movement-chart'].map(id=>[id,{id}]));
nodes['chart-data'] = {textContent:JSON.stringify({years:['2026'],series:[],assets:[{value:1234.56}],liquidity:[{value:-1234.56}]})};
nodes['movement-data'] = {textContent:JSON.stringify({labels:['Gain'],values:[-1234.56]})};
const echarts = {init:node=>({setOption:option=>options[node.id]=option,dispose(){}})};
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
console.log('Chart locale callbacks and HTMX redraw checks passed.');
