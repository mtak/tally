(() => {
  const palette = ["#307d6e", "#9cae9a", "#d7a761", "#8799c5", "#bd8f9d", "#90bfc2", "#b7b9a8"];
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
      const chart=echarts.init(history);charts.push(chart);
      chart.setOption({...common, tooltip:{...tooltipStyle,trigger:"axis",valueFormatter:v=>number.format(v)},
        grid:{left:70,right:15,top:18,bottom:62},
        xAxis:{type:"category",data:data.years,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ink,margin:16}},
        yAxis:{type:"value",axisLabel:{color:ink,formatter:v=>formats.compact.format(v)},
          splitLine:{lineStyle:{color:line,type:"dashed"}}},
        series:data.series.map(s=>({...s,type:"bar",stack:"total",barMaxWidth:48,emphasis:{focus:"series"}}))});
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
