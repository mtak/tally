(() => {
  const palette = ["#307d6e", "#9cae9a", "#d7a761", "#8799c5", "#bd8f9d", "#90bfc2", "#b7b9a8"];
  // HTMX updates dashboard filters without replacing the language/precision forms.
  document.addEventListener("submit", e => {
    const next = e.target.querySelector('input[name="next"]');
    if (next) next.value = window.location.pathname + window.location.search;
  });
  document.addEventListener("change", e => { if (e.target.matches("[data-auto-submit]")) e.target.form.requestSubmit(); });
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("tally-theme", theme); } catch {}
    draw();
  });
  function numberFormats() {
    const locale = document.documentElement.lang === "nl" ? "nl-NL" : "en-US";
    const digits = document.documentElement.dataset.showCents === "true" ? 2 : 0;
    return {
      money: new Intl.NumberFormat(locale, {style:"currency", currency:"EUR", minimumFractionDigits:digits, maximumFractionDigits:digits}),
      decimal: new Intl.NumberFormat(locale, {maximumFractionDigits:2}),
      compact: new Intl.NumberFormat(locale, {notation:"compact", maximumFractionDigits:1}),
      date: value => new Intl.DateTimeFormat(locale).format(new Date(value + "T00:00:00"))
    };
  }
  let charts = [];
  function draw() {
    charts.forEach(c => c.dispose()); charts = [];
    const source = document.getElementById("chart-data");
    if (!window.echarts) return;
    drawInvestment();
    drawMaturities();
    if (!source) { drawMovement(); return; }
    const data = JSON.parse(source.textContent);
    const style = getComputedStyle(document.documentElement);
    const ink = style.getPropertyValue("--muted").trim(), line = style.getPropertyValue("--line").trim();
    const formats = numberFormats(), number = formats.money;
    const tooltipStyle = {backgroundColor:style.getPropertyValue("--surface").trim(), borderColor:line, textStyle:{color:ink}};
    const common = {animation:false,color:palette, textStyle:{fontFamily:"-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif", color:ink},
      aria:{enabled:false}, tooltip:{...tooltipStyle,trigger:"item", valueFormatter:v => number.format(v)},
      legend:{bottom:0, icon:"roundRect", itemWidth:10, itemHeight:10, textStyle:{color:ink,fontSize:11}}};
    const history = document.getElementById("history-chart");
    if (history) {
      // Keep each full EUR label readable, including cents, on narrow screens.
      history.style.minWidth = Math.max(360, data.years.length * 170 + 100) + "px";
      const chart=echarts.init(history);charts.push(chart);
      const totals = data.totals || [];
      const totalText = index => totals[index] == null ? "" : number.format(totals[index] / 100);
      // Anchor above the positive stack, even when a negative category lowers net wealth.
      const labelPoints = totals.map((total,index) => total === null ? null : [index,
        data.series.reduce((sum,series)=>sum + Math.max(0, series.data[index] || 0), 0)]);
      chart.setOption({...common, legend:{...common.legend,selectedMode:false,data:data.series.map(series=>series.name)},
        tooltip:{...tooltipStyle,trigger:"axis",renderMode:"richText",confine:true,valueFormatter:v=>number.format(v),formatter:params=>{
          const index = params[0]?.dataIndex;
          if (index === undefined || totals[index] == null) return "";
          return [formats.date(data.dates[index]), ...data.series.map(series=>series.name + ": " + number.format(series.data[index])),
            data.total_label + ": " + totalText(index)].join("\n");
        }},
        grid:{left:70,right:30,top:45,bottom:62},
        xAxis:{type:"category",data:data.years,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ink,margin:16}},
        yAxis:{type:"value",axisLabel:{color:ink,formatter:v=>formats.compact.format(v)},
          splitLine:{lineStyle:{color:line,type:"dashed"}}},
        series:[...data.series.map(s=>({...s,type:"bar",stack:"total",barMaxWidth:48,emphasis:{focus:"series"}})),
          {name:data.total_label,type:"scatter",silent:true,symbolSize:0,tooltip:{show:false},data:labelPoints,
            label:{show:true,position:"top",distance:10,color:style.getPropertyValue("--ink").trim(),fontSize:12,fontWeight:600,
              formatter:params=>totalText(params.dataIndex)}}]});
    }
    const mixNode = document.getElementById("asset-mix-chart");
    if (mixNode && data.mix) {
      const mix = data.mix, chart = echarts.init(mixNode); charts.push(chart);
      chart.setOption({...common,
        legend:{...common.legend,type:"scroll"},
        tooltip:{...tooltipStyle,trigger:"axis",renderMode:"richText",confine:true,formatter:params=>{
          const index = params[0]?.dataIndex;
          if (index === undefined) return "";
          const lines = [formats.date(mix.dates[index])];
          for (const series of mix.series) {
            const point = series.data[index];
            if (point.value === null) continue;
            lines.push(series.name + ": " + formats.decimal.format(Number(point.value)) + "% · " + number.format(point.amount / 100));
            if (point.carried_dates.length) lines.push(mix.carried_label + ": " + point.carried_dates.map(formats.date).join(", "));
          }
          if (mix.series.every(s=>s.data[index].value === null)) lines.push(mix.unavailable_label);
          if (mix.missing[index].length) lines.push(mix.missing_label + ": " + mix.missing[index].join(", "));
          return lines.join("\n");
        }},
        grid:{left:55,right:15,top:18,bottom:62},
        xAxis:{type:"category",data:data.years,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ink}},
        yAxis:{type:"value",min:0,max:100,axisLabel:{color:ink,formatter:v=>formats.decimal.format(v)+"%"},splitLine:{lineStyle:{color:line,type:"dashed"}}},
        series:mix.series.map(s=>({...s,type:"bar",stack:"mix",barMaxWidth:48,emphasis:{focus:"series"},
          data:s.data.map(point=>({...point,value:point.value === null ? null : Number(point.value)}))}))});
    }
    for (const [id,values] of [["assets-chart",data.assets],["liquidity-chart",data.liquidity]]) {
      const node=document.getElementById(id);if(!node)continue;
      const chart=echarts.init(node);charts.push(chart);
      if(id==="liquidity-chart" && values.some(v=>v.value<0)) {
        chart.setOption({...common,grid:{left:100,right:15,top:20,bottom:30},
          xAxis:{type:"value",axisLabel:{color:ink,formatter:v=>formats.decimal.format(v)},splitLine:{lineStyle:{color:line}}},
          yAxis:{type:"category",data:values.map(v=>v.name),axisLabel:{color:ink},axisLine:{lineStyle:{color:line}}},
          series:[{type:"bar",data:values.map(v=>v.value)}]}); continue;
      }
      chart.setOption({...common,series:[{type:"pie",radius:["49%","72%"],center:["50%","42%"],
        avoidLabelOverlap:true,itemStyle:{borderRadius:3,borderColor:style.getPropertyValue("--surface").trim(),borderWidth:3},
        label:{show:false},emphasis:{label:{show:true,fontSize:16,fontWeight:600,formatter:params=>formats.decimal.format(params.percent)+"%"}},
        data:values}]});
    }
  }

  function drawMaturities() {
    const source = document.getElementById("maturity-data");
    if (!source) return;
    const data = JSON.parse(source.textContent), formats = numberFormats();
    const style = getComputedStyle(document.documentElement), ink = style.getPropertyValue("--muted").trim();
    const line = style.getPropertyValue("--line").trim();
    const colors = {private:style.getPropertyValue("--private").trim(), business:style.getPropertyValue("--business").trim()};
    const tooltip = {renderMode:"richText",confine:true,backgroundColor:style.getPropertyValue("--surface").trim(),
      borderColor:line,textStyle:{color:ink}};
    const quarterNode = document.getElementById("maturity-quarter-chart");
    if (quarterNode) {
      const chart = echarts.init(quarterNode); charts.push(chart);
      chart.setOption({animation:false,aria:{enabled:false},
        legend:{bottom:0,textStyle:{color:ink}},grid:{left:70,right:20,top:20,bottom:70},
        tooltip:{...tooltip,trigger:"axis",valueFormatter:value=>formats.money.format(value)},
        xAxis:{type:"category",data:data.quarters.map(q=>q.label),axisLabel:{color:ink},axisLine:{lineStyle:{color:line}},axisTick:{show:false}},
        yAxis:{type:"value",axisLabel:{color:ink,formatter:value=>formats.compact.format(value)},splitLine:{lineStyle:{color:line,type:"dashed"}}},
        series:Object.keys(data.groups).map(group=>({name:data.groups[group],type:"bar",stack:"release",barMaxWidth:50,
          itemStyle:{color:colors[group]},data:data.quarters.map(q=>q[group]/100)}))});
    }
    const node = document.getElementById("maturity-timeline-chart");
    const rows = data.rows.filter(row=>row.start || row.end);
    if (!node || !rows.length) { if (node) node.hidden = true; return; }
    node.style.height = Math.max(240, rows.length * 42 + 95) + "px";
    const timestamp = date=>Date.parse(date + "T00:00:00Z");
    const dateLabel = value=>formats.date(new Date(value).toISOString().slice(0,10));
    const chart = echarts.init(node); charts.push(chart);
    const dates = rows.flatMap(row=>[row.start,row.end].filter(Boolean).map(timestamp));
    chart.setOption({animation:false,useUTC:true,aria:{enabled:false},grid:{left:135,right:25,top:20,bottom:65},
      tooltip:{...tooltip,trigger:"item",formatter:params=>{
        const row = rows[params.dataIndex], labels = data.labels;
        return [row.name + " · " + row.owner, data.groups[row.group], row.status,
          labels.balance + ": " + (row.amount === null ? labels.unknown : formats.money.format(row.amount/100)),
          labels.observed + ": " + (row.observed ? formats.date(row.observed) : labels.unknown) + (row.stale ? " · " + labels.carried : ""),
          labels.start + ": " + (row.start ? formats.date(row.start) : labels.unknown),
          labels.end + ": " + (row.end ? formats.date(row.end) : labels.unknown)].join("\n");
      }},
      xAxis:{type:"time",min:Math.min(...dates)-86400000,max:Math.max(...dates)+86400000,
        axisLabel:{color:ink,formatter:dateLabel,hideOverlap:true},axisLine:{lineStyle:{color:line}},splitLine:{lineStyle:{color:line,type:"dashed"}}},
      yAxis:{type:"category",inverse:true,data:rows.map(row=>row.name),axisLabel:{color:ink,width:110,overflow:"truncate"},axisTick:{show:false},axisLine:{show:false}},
      series:[{type:"custom",data:rows.map((row,index)=>[index,timestamp(row.start || row.end),timestamp(row.end || row.start)]),
        renderItem:(params,api)=>{
          const row = rows[params.dataIndex], start = api.coord([api.value(1),api.value(0)]), end = api.coord([api.value(2),api.value(0)]);
          const color = colors[row.group];
          const children = [];
          if (row.start && row.end) children.push({type:"line",shape:{x1:start[0],y1:start[1],x2:end[0],y2:end[1]},style:{stroke:color,lineWidth:7}});
          if (row.start) children.push({type:"circle",shape:{cx:start[0],cy:start[1],r:5},style:{fill:color}});
          if (row.end) children.push({type:"circle",shape:{cx:end[0],cy:end[1],r:6},style:{fill:color,stroke:ink,lineWidth:1}});
          return {type:"group",children};
        }}]});
  }

  function drawInvestment() {
    const source = document.getElementById("investment-data"), node = document.getElementById("investment-chart");
    if (!source || !node) return;
    const data = JSON.parse(source.textContent), formats = numberFormats();
    const style = getComputedStyle(document.documentElement), ink = style.getPropertyValue("--muted").trim();
    const line = style.getPropertyValue("--line").trim();
    // UTC timestamps keep calendar spacing stable across daylight-saving changes.
    const timestamps = data.dates.map(date=>Date.parse(date + "T00:00:00Z"));
    const dateLabel = value=>formats.date(new Date(value).toISOString().slice(0, 10));
    const chart = echarts.init(node); charts.push(chart);
    chart.setOption({animation:false,color:palette,aria:{enabled:false},
      legend:{bottom:0,type:"scroll",textStyle:{color:ink,fontSize:11}},
      grid:{left:70,right:20,top:20,bottom:75},
      tooltip:{trigger:"axis",renderMode:"richText",confine:true,
        backgroundColor:style.getPropertyValue("--surface").trim(),borderColor:line,textStyle:{color:ink},
        formatter:params=>{
          const index = params[0]?.dataIndex;
          if (index === undefined) return "";
          return [formats.date(data.dates[index]), ...data.series.map(series=>series.name + ": " +
            (series.data[index] === null ? data.unknown_label : formats.money.format(series.data[index] / 100)))].join("\n");
        }},
      xAxis:{type:"time",axisLabel:{color:ink,formatter:dateLabel,hideOverlap:true},axisLine:{lineStyle:{color:line}},axisTick:{show:false}},
      yAxis:{type:"value",axisLabel:{color:ink,formatter:v=>formats.compact.format(v)},splitLine:{lineStyle:{color:line,type:"dashed"}}},
      series:data.series.map(series=>({name:series.name,type:"line",smooth:false,connectNulls:false,
        showSymbol:true,showAllSymbol:true,symbolSize:7,
        data:series.data.map((amount,index)=>[timestamps[index],amount === null ? null : amount / 100])}))});
  }

  function drawMovement() {
    const source=document.getElementById("movement-data"), node=document.getElementById("movement-chart");
    if (!source || !node) return;
    const data=JSON.parse(source.textContent);
    const style=getComputedStyle(document.documentElement), ink=style.getPropertyValue("--muted").trim();
    const line=style.getPropertyValue("--line").trim();
    const formats=numberFormats(), money=formats.money;
    const c=echarts.init(node);charts.push(c);
    c.setOption({animation:false,aria:{enabled:false},grid:{left:75,right:15,top:20,bottom:85},
      tooltip:{backgroundColor:style.getPropertyValue("--surface").trim(),borderColor:line,textStyle:{color:ink},trigger:"axis",formatter:params=>money.format(data.values[params[0].dataIndex])},
      xAxis:{type:"category",data:data.labels,axisLabel:{color:ink,interval:0,rotate:18,fontSize:10},axisTick:{show:false},axisLine:{lineStyle:{color:line}}},
      yAxis:{type:"value",axisLabel:{color:ink,formatter:v=>formats.compact.format(v)},splitLine:{lineStyle:{color:line}}},
      series:[{type:"bar",barMaxWidth:50,data:data.values.map(value=>({
        value,itemStyle:{color:value>=0?"#307d6e":"#bd8f9d"}
      }))}]});
    c.on("click", params => {
      const details = document.getElementById(data.detail_ids?.[params.dataIndex]);
      if (!details) return;
      details.open = true;
      details.querySelector("summary").focus();
      details.scrollIntoView({behavior:"smooth", block:"nearest"});
    });
  }
  document.addEventListener("htmx:afterSwap",draw);
  window.addEventListener("resize",()=>charts.forEach(c=>c.resize()));
  draw();
})();
