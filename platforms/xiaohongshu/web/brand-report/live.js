(() => {
  const $ = s => document.querySelector(s);
  const api = '/v1/xhs/weekly';
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const name = {positive:'正向',neutral:'中性',negative:'负向',running:'运行中',paused:'已暂停',partial:'部分完成',completed:'采集完成',rate_limited:'平台限流，已暂停',cooldown:'冷却等待中',login_required:'需要登录',verification_required:'需要平台验证',failed:'任务失败',pause_requested:'正在暂停'};
  let job = null, report = null, offset = 0, busy = false;
  function message(s, error=false) { $('#message').textContent=s; $('#message').className=s?`notice ${error?'error':''}`:''; }
  async function call(path, method='GET', body) {
    const r=await fetch(api+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    const data=await r.json();
    if(!r.ok) throw Error(typeof data.detail==='string'?data.detail:data.message||JSON.stringify(data.detail));
    return data;
  }
  function metric(value,label) { return `<div class="metric"><b>${esc(value??'待计算')}</b><span>${esc(label)}</span></div>`; }
  async function refresh() {
    if(busy) return;
    busy=true;
    try {
      const jobs=await call('/jobs');
      if(!jobs.length){$('#job-meta').textContent='尚无采集任务，填写配置后启动。';return;}
      job=jobs[0];
      $('#job-meta').textContent=`${name[job.status]||job.status} · ${job.stage} · 更新于 ${new Date(job.updated_at).toLocaleString('zh-CN')}`;
      $('#progress').innerHTML=metric(job.notes,'去重笔记')+metric(job.comments,'已保存评论（含回复）')+metric(job.notes_complete,'详情与评论采样已完成')+metric(job.notes_incomplete,'待完成当前采集目标');
      $('#search-progress').innerHTML=job.searches.map(s=>`<tr><td>${esc(s.keyword)}</td><td>${esc(s.sort||'time_descending')}</td><td>${esc(s.nonempty_pages??0)}</td><td>${esc(s.fetched_pages)} / ${esc(s.requested_pages)}</td><td>${esc(s.stop_reason||s.status)}</td></tr>`).join('');
      $('#model-status').textContent=`分析状态：${job.analysis_status||'未运行'} ${job.analysis_stage||''} ${job.analysis_error||''}`;
      $('#pause').disabled=job.status!=='running';$('#resume').disabled=['running','pause_requested'].includes(job.status);
      $('#config button').disabled=['running','pause_requested'].includes(job.status);
      $('#analyze').disabled=job.analysis_status==='running';$('#train').disabled=job.analysis_status==='running';
      report=await call(`/jobs/${job.job_id}/report`);
      $('h1').textContent=`${report.config.primary} 品牌营销周报`;
      $('#period').textContent=`${report.config.week_start} 至 ${report.config.week_end} · 数据快照 ${new Date(report.generated_at).toLocaleString('zh-CN')}`;
      $('#brand-kpis').innerHTML=report.brands.map(b=>`<div class="metric"><span>${esc(b.brand)}</span><b>${esc(b.volume)}</b><span>本周笔记 · 历史采集 ${esc(b.collected_history_notes)} 篇</span><p>累计互动 ${esc(b.interactions??'字段待补全')}</p><p>正向率 ${b.positive_rate===null?'待标注与训练':(b.positive_rate*100).toFixed(1)+'%'}</p></div>`).join('');
      $('#quality').textContent=`已取得发布时间 ${report.quality.dated_notes} 篇，日期缺失 ${report.quality.undated_notes} 篇；本周文本 ${report.quality.weekly_texts} 条。${report.stale?'采集仍在更新，模型结果来自上次分析。':''}`;
      $('#topics').innerHTML=report.topics.length?report.topics.slice(0,6).map(t=>`<article class="topic"><h3>${t.keywords.slice(0,4).map(esc).join(' · ')}</h3><p>${t.weekly_texts} 条本周文本 · ${t.weekly_notes} 篇关联笔记</p><details><summary>查看原文证据</summary>${t.evidence.map(e=>`<blockquote>${esc(e.text)} <a target="_blank" rel="noopener noreferrer" href="https://www.xiaohongshu.com/explore/${encodeURIComponent(e.note_id)}">查看笔记</a></blockquote>`).join('')}</details></article>`).join(''):'<p>暂无本周话题结果。可先采集详情与评论，再运行 BERTopic；样本不足时保持空结果。</p>';
      $('#history-topics').innerHTML=(report.history_topics||[]).slice(0,6).map(t=>`<article class="topic"><h3>${t.keywords.slice(0,4).map(esc).join(' · ')}</h3><p>跨期样本 ${t.text_count} 条</p><details><summary>查看跨期原文</summary>${t.evidence.map(e=>`<blockquote>${esc(e.text)}<br>${esc(e.date||'日期缺失')}</blockquote>`).join('')}</details></article>`).join('')||'<p>模型训练完成后显示。</p>';
      const svm=report.models.sentiment;
      if(svm.metrics){const m=svm.metrics;$('#evaluation').innerHTML=`<p>训练 ${m.train_count} 条 · 测试 ${m.test_count} 条 · 按笔记分组隔离</p><p>准确率 ${(m.classification_report.accuracy*100).toFixed(1)}% · 宏平均 F1 ${m.classification_report['macro avg']['f1-score'].toFixed(3)}</p><p>${m.independent_human_ground_truth?'标签来源：人工复核':'标签含辅助标注，指标仅相对当前标注集，不等同独立人工验证'}</p><pre>${esc(JSON.stringify(m.confusion_matrix,null,2))}</pre>`;}else $('#evaluation').textContent='SVM 尚待真实评论标签。请标注至少45条、每类至少8条，并覆盖多个笔记；满足分组测试条件后再训练。';
      await comments();
    } catch(e){message(e.message,true);}finally{busy=false;}
  }
  async function comments(){
    if(!job)return;
    const data=await call(`/jobs/${job.job_id}/evidence?offset=${offset}`);
    $('#label-status').textContent=`评论 ${data.total?offset+1:0}—${Math.min(offset+30,data.total)} / ${data.total}；点击标签保存人工复核结果。`;
    $('#labels').innerHTML=data.items.map(d=>`<article class="comment"><div><p>${esc(d.text)}</p><small>${esc(d.brands.join(' / '))} · ${esc(d.date||'日期缺失')} · 笔记 ${esc(d.note_id)}</small></div><div class="actions">${['positive','neutral','negative'].map(l=>`<button data-id="${esc(d.id)}" data-label="${l}" class="${d.annotation?.label===l?'chosen':''}">${name[l]}</button>`).join('')}</div></article>`).join('')||'<p>评论仍在采集中。</p>';
    $('#prev').disabled=offset===0;$('#next').disabled=offset+30>=data.total;
  }
  $('#labels').addEventListener('click',async e=>{const b=e.target.closest('[data-label]');if(!b||!job)return;try{await call(`/jobs/${job.job_id}/labels`,'POST',{document_id:b.dataset.id,label:b.dataset.label});await comments();}catch(err){message(err.message,true);}});
  $('#config').addEventListener('submit',async e=>{e.preventDefault();const f=new FormData(e.target);try{job=await call('/jobs','POST',{primary:f.get('primary').trim(),competitors:f.get('competitors').split(/[,，]/).map(s=>s.trim()).filter(Boolean),search_pages:Number(f.get('search_pages')),week_start:f.get('week_start'),week_end:f.get('week_end')});message('采集任务已启动，数据按页保存。');await refresh();}catch(err){message(err.message,true);}});
  for(const action of ['pause','resume','analyze','train'])$('#'+action).addEventListener('click',async()=>{if(!job)return;try{await call(`/jobs/${job.job_id}/${action}`,'POST');message('任务状态已更新。');await refresh();}catch(e){message(e.message,true);}});
  $('#reload').addEventListener('click',refresh);$('#next').addEventListener('click',()=>{offset+=30;comments().catch(e=>message(e.message,true));});$('#prev').addEventListener('click',()=>{offset=Math.max(0,offset-30);comments().catch(e=>message(e.message,true));});
  $('#export').addEventListener('click',()=>{if(!report)return;const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`${report.config.primary}-${report.config.week_start}-weekly.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  refresh();setInterval(()=>{if(!document.hidden)refresh();},15000);
})();
