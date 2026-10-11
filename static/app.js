(() => {
  const palette = ["#307d6e", "#9cae9a", "#d7a761", "#8799c5", "#bd8f9d", "#90bfc2", "#b7b9a8"];
  try { document.documentElement.dataset.theme = localStorage.getItem("tally-theme") || "light"; } catch {}
  document.addEventListener("change", e => { if (e.target.matches("[data-auto-submit]")) e.target.form.requestSubmit(); });
  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("tally-theme", theme); } catch {}
    draw();
  });
  let charts = [];
  function draw() {
    charts.forEach(c => c.dispose()); charts = [];
    const source = document.getElementById("chart-data");
    if (!window.echarts) return;
    if (!source) { drawMovement(); return; }
    const data = JSON.parse(source.textContent);
    const style = getComputedStyle(document.documentElement);
    const ink = style.getPropertyValue("--muted").trim(), line = style.getPropertyValue("--line").trim();
    const lang = document.documentElement.lang;
    const number = new Intl.NumberFormat(lang, {style:"currency", currency:"EUR", maximumFractionDigits:0});
    const common = {animation:false,color:palette, textStyle:{fontFamily:"-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif", color:ink},
      aria:{enabled:false}, tooltip:{trigger:"item", valueFormatter:v => number.format(v)},
      legend:{bottom:0, icon:"roundRect", itemWidth:10, itemHeight:10, textStyle:{color:ink,fontSize:11}}};
    const history = document.getElementById("history-chart");
    if (history) {
      const chart=echarts.init(history);charts.push(chart);
      chart.setOption({...common, tooltip:{trigger:"axis",valueFormatter:v=>number.format(v)},
        grid:{left:70,right:15,top:18,bottom:62},
        xAxis:{type:"category",data:data.years,axisLine:{show:false},axisTick:{show:false},axisLabel:{color:ink,margin:16}},
        yAxis:{type:"value",axisLabel:{color:ink,formatter:v=>new Intl.NumberFormat(lang,{notation:"compact",maximumFractionDigits:1}).format(v)},
          splitLine:{lineStyle:{color:line,type:"dashed"}}},
        series:data.series.map(s=>({...s,type:"bar",stack:"total",barMaxWidth:48,emphasis:{focus:"series"}}))});
    }
    for (const [id,values] of [["assets-chart",data.assets],["liquidity-chart",data.liquidity]]) {
      const node=document.getElementById(id);if(!node)continue;
      const chart=echarts.init(node);charts.push(chart);
      if(id==="liquidity-chart" && values.some(v=>v.value<0)) {
        chart.setOption({...common,grid:{left:100,right:15,top:20,bottom:30},
          xAxis:{type:"value"},yAxis:{type:"category",data:values.map(v=>v.name)},
          series:[{type:"bar",data:values.map(v=>v.value)}]}); continue;
      }
      chart.setOption({...common,series:[{type:"pie",radius:["49%","72%"],center:["50%","42%"],
        avoidLabelOverlap:true,itemStyle:{borderRadius:3,borderColor:style.getPropertyValue("--surface").trim(),borderWidth:3},
        label:{show:false},emphasis:{label:{show:true,fontSize:16,fontWeight:600,formatter:"{d}%"}},
        data:values}]});
    }
  }

  function drawMovement() {
    const source=document.getElementById("movement-data"), node=document.getElementById("movement-chart");
    if (!source || !node) return;
    const data=JSON.parse(source.textContent), last=data.values.length-1;
    let running=data.values[0];
    const base=[],positive=[],negative=[];
    data.values.forEach((value,i)=>{
      if(i===0 || i===last){base.push(Math.min(0,value));positive.push(value>=0?value:0);negative.push(value<0?-value:0);}
      else { const next=running+value; base.push(Math.min(running,next));positive.push(value>=0?value:0);negative.push(value<0?-value:0);running=next;}
    });
    const style=getComputedStyle(document.documentElement), ink=style.getPropertyValue("--muted").trim();
    const money=new Intl.NumberFormat(document.documentElement.lang,{style:"currency",currency:"EUR",maximumFractionDigits:0});
    const c=echarts.init(node);charts.push(c);
    c.setOption({animation:false,aria:{enabled:false},grid:{left:75,right:15,top:20,bottom:85},
      tooltip:{trigger:"axis",formatter:params=>money.format(data.values[params[0].dataIndex])},
      xAxis:{type:"category",data:data.labels,axisLabel:{color:ink,interval:0,rotate:18,fontSize:10},axisTick:{show:false}},
      yAxis:{type:"value",axisLabel:{color:ink,formatter:v=>new Intl.NumberFormat(document.documentElement.lang,{notation:"compact"}).format(v)}},
      series:[{type:"bar",stack:"movement",data:base,itemStyle:{color:"transparent"},emphasis:{itemStyle:{color:"transparent"}},silent:true},
      {type:"bar",stack:"movement",data:positive,itemStyle:{color:"#307d6e"},barMaxWidth:50},
      {type:"bar",stack:"movement",data:negative,itemStyle:{color:"#bd8f9d"},barMaxWidth:50}]});
  }
  document.addEventListener("htmx:afterSwap",draw);
  window.addEventListener("resize",()=>charts.forEach(c=>c.resize()));
  draw();
})();
