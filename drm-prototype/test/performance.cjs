'use strict';
// Controlled local comparison: one active start page plus twelve restored tabs.
const {app}=require('electron'),fs=require('node:fs');
const wait=ms=>new Promise(r=>setTimeout(r,ms));
module.exports=async({win,tabs,newTab})=>{
 for(let i=0;i<12;i++)newTab('vaultie://home',false);
 await wait(3000);app.getAppMetrics();await wait(2000);
 const metrics=app.getAppMetrics();
 const result={platform:process.platform,scenario:'1 active + 12 background home tabs',tabs:tabs.size,loadedViews:[...tabs.values()].filter(t=>t.view).length,processes:metrics.length,workingSetMiB:metrics.reduce((sum,m)=>sum+(m.memory?.workingSetSize||0),0)/1024,cpuPercent:metrics.reduce((sum,m)=>sum+(m.cpu?.percentCPUUsage||0),0)};
 if(process.env.VAULTIE_PERF_SHOT){fs.writeFileSync(process.env.VAULTIE_PERF_SHOT,(await win.capturePage()).toPNG());const t=[...tabs.values()][0];fs.writeFileSync(process.env.VAULTIE_PERF_SHOT+'.home.png',(await t.view.webContents.capturePage()).toPNG());}
 fs.writeFileSync(process.env.VAULTIE_PERF_RESULT,JSON.stringify(result,null,2));console.log(JSON.stringify(result));app.exit(0);
};
