(() => {
  'use strict';
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const API = '/v1/xhs/weekly';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const format = value => value == null ? '—' : Number(value).toLocaleString('zh-CN');
  const percent = value => value == null ? '—' : `${(value * 100).toFixed(1)}%`;
  const localTime = value => value ? new Date(value).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '—';
  const colors = {positive:'#299467',neutral:'#a4b2c4',negative:'#cf5569',pending:'#cf9a39'};
  const names = {positive:'正向',neutral:'中性',negative:'负向',pending:'待复核',running:'采集中',completed:'采集完成',partial:'部分完成',paused:'已暂停',pause_requested:'正在暂停',verification_required:'平台验证待处理',login_required:'需要登录',rate_limited:'平台限流，已暂停',cooldown:'冷却等待中',failed:'任务异常',interrupted:'任务已中断'};
  const stages = {preparing:'准备数据',svm_grouped_cv:'SVM 分组交叉验证',embeddings:'更新文本语义向量',bertopic_fit:'BERTopic 话题训练',bertopic:'话题聚类',bertopic_save_reload:'模型保存与加载校验',finished:'已完成'};
  const state = {job:null,report:null,view:null,scope:'week',brand:'libtv',week:'2026-10-19',snapshot:null,busy:false,archiveStamp:null};
  let toastTimer;
  function toast(message) { $('#toast').textContent=message;$('#toast').classList.add('visible');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('visible'),3800); }
  async function api(path, method='GET', body) {
    const response=await fetch(API+path,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
    const data=await response.json();
    if(!response.ok) throw Error(typeof data.detail==='string'?data.detail:data.message||'请求未完成，请检查工作台状态');
    return data;
  }
  function metric(value,label) { return `<div class="model-metric"><strong>${esc(value)}</strong><span>${esc(label)}</span></div>`; }
  function spark(selector,values) {
    const maximum=Math.max(1,...values.filter(v=>v!=null));
    $(selector).innerHTML=values.map(v=>`<span style="height:${v==null||v===0?0:Math.max(3,v/maximum*100)}%;min-height:0"></span>`).join('');
  }
  function trend(series) {
    const w=690,h=210,left=39,right=49,top=15,bottom=28,cw=w-left-right,ch=h-top-bottom;
    const volumeMax=Math.max(1,...series.map(d=>d.volume));
    const interactionValues=series.map(d=>d.interactions).filter(v=>v!=null);
    const interactionMax=Math.max(1,...interactionValues);
    const x=i=>left+(series.length<=1?cw/2:i*cw/(series.length-1));
    const y=(value,max)=>top+ch*(1-value/max);
    const line=(key,max)=>{let start=true;return series.map((d,i)=>{if(d[key]==null){start=true;return '';}const p=`${start?'M':'L'}${x(i).toFixed(1)},${y(d[key],max).toFixed(1)}`;start=false;return p;}).join(' ');};
    let svg='';
    for(let i=0;i<=4;i++) {
      const yy=top+ch*i/4;
      svg+=`<line x1="${left}" x2="${w-right}" y1="${yy}" y2="${yy}" stroke="#e5ecf5" stroke-dasharray="3 4"/><text x="${left-8}" y="${yy+3}" text-anchor="end" fill="#5d7595" font-size="9">${Math.round(volumeMax*(1-i/4))}</text><text x="${w-right+8}" y="${yy+3}" fill="#8d6d37" font-size="9">${Math.round(interactionMax*(1-i/4)).toLocaleString('zh-CN')}</text>`;
    }
    if(series.length) {
      const voice=line('volume',volumeMax);
      svg+=`<path d="${voice} L${x(series.length-1)},${top+ch} L${x(0)},${top+ch} Z" fill="#2d6cdf" opacity=".065" stroke="none"/><path d="${voice}" fill="none" stroke="#3475da" stroke-width="2.2" vector-effect="non-scaling-stroke"/><path d="${line('interactions',interactionMax)}" fill="none" stroke="#c78924" stroke-width="2" vector-effect="non-scaling-stroke"/>`;
      series.forEach((d,i)=>{
        const title=`${d.date}：声量 ${d.volume} 篇；采集时累计互动 ${d.interactions==null?'字段未齐':d.interactions}`;
        svg+=`<circle cx="${x(i)}" cy="${y(d.volume,volumeMax)}" r="3.3" fill="white" stroke="#3475da" stroke-width="1.5"><title>${esc(title)}</title></circle>`;
        if(d.interactions!=null)svg+=`<circle cx="${x(i)}" cy="${y(d.interactions,interactionMax)}" r="2.8" fill="white" stroke="#c78924" stroke-width="1.3"><title>${esc(title)}</title></circle>`;
        if(series.length<=7||i%2===0||i===series.length-1)svg+=`<text x="${x(i)}" y="${h-5}" text-anchor="middle" fill="#657c99" font-size="9">${d.date.slice(5).replace('-','.')}</text>`;
      });
    }
    $('#trend-chart').innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">${svg}</svg>`;
    $('#trend-chart').setAttribute('aria-label',series.map(d=>`${d.date} ${d.volume}篇，累计互动${d.interactions??'缺失'}`).join('；'));
  }
  function topicMood(t) {
    if(t.risk_candidate)return 'negative';
    const keys=['positive','neutral','negative'];
    if(!keys.some(key=>(t.sentiment[key]||0)>0))return 'pending';
    return keys.reduce((a,b)=>(t.sentiment[b]||0)>(t.sentiment[a]||0)?b:a,'positive');
  }
  function renderTopics(view) {
    $('#topic-table').innerHTML=view.topics.slice(0,5).map((t,i)=>{const mood=topicMood(t);return `<tr><td><span class="topic-name"><i class="rank ${i<3?'top':''}">${i+1}</i><button class="topic-link" data-topic="${t.id}" title="${esc(t.title)}">${esc(t.title)}</button></span></td><td class="numeric">${format(t.text_count)}</td><td class="numeric">${format(t.note_count)}</td><td><span class="pill ${mood}">${t.risk_candidate?'需复核':names[mood]}</span></td></tr>`;}).join('')||'<tr><td colspan="4">当前范围暂无已分配话题，待模型更新。</td></tr>';
    $('#topic-note').textContent=`当前范围识别 ${view.topics.length} 个话题；${view.sample_quality.unassigned_topic_texts} 条文本未分配或属于噪声。话题编号仅在同次训练中有效。`;
    $('#expanded-topics').innerHTML=view.topics.map(t=>`<article class="expanded-topic"><button data-topic="${t.id}">${esc(t.title)}</button><p>${format(t.text_count)} 条文本 · ${format(t.note_count)} 篇笔记 · 关键词 ${t.keywords.map(esc).join(' / ')}</p></article>`).join('')||'<p class="empty">暂无话题结果。</p>';
  }
  function renderSentiment(view) {
    const dist=view.sentiment,valid=dist.positive+dist.neutral+dist.negative;
    let angle=0;
    const sections=['positive','neutral','negative'].map(key=>{const start=angle;angle+=valid?dist[key]/valid*360:0;return `${colors[key]} ${start}deg ${angle}deg`;});
    $('#donut').style.background=valid?`conic-gradient(${sections.join(',')})`:'#e5ebf3';
    $('#donut-center').textContent=percent(view.kpis.positive_rate);
    $('#donut').setAttribute('aria-label',`正向${dist.positive}条，中性${dist.neutral}条，负向${dist.negative}条，待复核${dist.pending}条`);
    $('#sentiment-legend').innerHTML=['positive','neutral','negative','pending'].map(key=>`<div><i style="background:${colors[key]}"></i>${names[key]}<strong>${format(dist[key])}</strong></div>`).join('');
    $('#sentiment-subtitle').textContent=`环图含 ${format(valid)} 条已判定评论；${format(dist.pending)} 条待复核另列`;
    $('#aspect-cloud').innerHTML=view.aspects.map(a=>`<span class="aspect-chip" title="按关键词规则命中${a.count}条评论">${esc(a.name)}<b>${format(a.count)}</b></span>`).join('')||'<p class="chart-note">等待足够评价文本</p>';
  }
  function renderActions(view) {
    const key=`brand-pulse-actions:${state.job.job_id}:${view.brand}:${view.scope}:${view.period[0]}`;
    let done={};try{done=JSON.parse(localStorage.getItem(key)||'{}');}catch{}
    $('#actions').innerHTML=view.actions.map(a=>`<div class="action-row ${done[a.id]?'done':''}"><input type="checkbox" id="action-${esc(a.id)}" data-action-id="${esc(a.id)}" ${done[a.id]?'checked':''}><label for="action-${esc(a.id)}"><strong>${esc(a.title)}</strong><small>${esc(a.owner)} · 本期建议</small></label><span class="priority ${a.priority==='高'?'':'normal'}">${esc(a.priority)}</span></div>`).join('');
    $('#action-count').textContent=`${view.actions.filter(a=>!done[a.id]).length} 项待处理`;
    $('#actions').dataset.storageKey=key;
  }
  function renderCollection(job) {
    const status=names[job.status]||job.status;
    $('#health-text').textContent=status;
    $('#health-dot').style.background=job.status==='running'?'#5ad39a':job.status==='completed'?'#5ad39a':'#f1ba60';
    const commentScope=job.config?.comment_page_limit != null ? `前 ${job.config.comment_page_limit} 页主评论及随页回复（保留此前数据）` : '全部可获取主评论与回复';
    $('#collection-description').textContent=`${state.snapshot?'实时采集进度 · ':''}${status} · ${format(job.notes_complete)}/${format(job.notes)} 篇完成当前采集目标 · ${commentScope}${job.notes_deferred?' · 延后 '+format(job.notes_deferred)+' 篇':''}${job.cooldown_until?' · 预计 '+localTime(job.cooldown_until)+' 后自动续采':''} · 最后更新 ${localTime(job.updated_at)}`;
    $('#collection-metrics').innerHTML=[[job.notes,'搜索去重笔记'],[job.comments,'已保存主评论与回复'],[job.notes_complete,'详情与评论采样已完成'],[job.notes_incomplete,'待完成当前采集目标']].map(([v,l])=>`<div><b>${format(v)}</b><span>${l}</span></div>`).join('');
    const sortNames={general:'综合排序',time_descending:'最新发布',popularity_descending:'最多点赞'};
    const stops={upstream_end:'平台返回结束',target_reached:'当前排序目标已达',repeated_page:'重复页，保留断点',empty_nonterminal:'异常空页，待确认'};
    $('#collection-table').innerHTML=job.searches.map(s=>`<tr><td>${esc(s.keyword)}</td><td>${esc(sortNames[s.sort]||s.sort)}</td><td class="numeric">${format(s.nonempty_pages??0)}</td><td class="numeric">${format(s.fetched_pages)}</td><td>${esc(stops[s.stop_reason]||s.status)}</td></tr>`).join('');
    $('#pause').disabled=!['running','cooldown'].includes(job.status);
    $('#resume').disabled=['running','pause_requested','cooldown'].includes(job.status);
    const training=job.analysis_status==='running';
    $('#run-topics').disabled=training;$('#train-svm').disabled=training;
    $('#training-state').textContent=state.snapshot?`当前显示保存于 ${localTime(state.report.generated_at)} 的归档模型；继续训练会基于实时数据生成新快照。`:training?`正在${stages[job.analysis_stage]||job.analysis_stage||'训练'}，完成后自动刷新模型结果。`:`${job.analysis_status==='failed'?'上次训练异常：'+job.analysis_error:'最新分析完成于 '+localTime(job.analysis_finished_at)}。可继续训练并生成新快照。`;
  }
  function renderModels(report) {
    const topic=report.models.topic,metrics=report.models.sentiment.metrics;
    $('#topic-model-metrics').innerHTML=metric(format(topic.fit_sample_size),'去重训练文本')+metric(format(topic.topic_count),'发现话题')+metric(format(topic.noise_count),'噪声文本');
    $('#topic-persistence').textContent=topic.reload_verified?'完整话题管线已保存并通过加载预测验证；编码器使用固定 MiniLM 权重。':topic.state==='trained'?'话题已拟合，完整模型加载验证尚待本次训练完成。':'模型尚未完成训练。';
    if(!metrics){$('#svm-model-metrics').innerHTML='<p>等待有效情感标签</p>';$('#confusion-matrix').textContent='暂无测试结果';$('#class-scores').innerHTML='';$('#label-provenance').textContent='当前任务尚未训练情感分类器。';$('#model-comparison').textContent='';return;}
    const cr=metrics.classification_report;
    $('#svm-model-metrics').previousElementSibling.textContent=metrics.features?.includes('MiniLM')?'字符 TF-IDF ＋ 固定 MiniLM 语义特征 · 按笔记分组验证':'字符 TF-IDF · 按笔记分组验证';
    $('#svm-model-metrics').innerHTML=metric(format(metrics.train_count),'训练样本')+metric(percent(cr.accuracy),'测试准确率')+metric(cr['macro avg']['f1-score'].toFixed(3),'宏平均 F1');
    const sources=metrics.label_sources||{};
    $('#label-provenance').textContent=`${format(sources.human_review||0)} 条人工标注，${format(sources.ai_assisted_review||0)} 条辅助标注；${format(metrics.test_count)} 条按笔记隔离的测试样本。${metrics.independent_human_ground_truth?'本轮测试标签均来自人工复核。':'测试集含辅助标签，结果用于原型验证。'}${metrics.reload_verified?'分类器已保存并通过加载校验。':''}`;
    const keys=metrics.label_order,maximum=Math.max(1,...metrics.confusion_matrix.flat());
    $('#confusion-matrix').innerHTML=`<table class="matrix"><thead><tr><th>真实 / 预测</th>${keys.map(k=>`<th>${names[k]}</th>`).join('')}</tr></thead><tbody>${metrics.confusion_matrix.map((row,i)=>`<tr><th>${names[keys[i]]}</th>${row.map(value=>`<td style="background:rgba(45,108,223,${.05+value/maximum*.24})">${value}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    $('#class-scores').innerHTML=keys.map(k=>`<div class="class-score"><div class="class-score-top"><span>${names[k]}</span><strong>F1 ${cr[k]['f1-score'].toFixed(3)}</strong></div><div class="bar-track"><span style="width:${cr[k]['f1-score']*100}%;background:${colors[k]}"></span></div><small>召回率 ${percent(cr[k].recall)} · 测试样本 ${format(cr[k].support)} 条</small></div>`).join('');
    const prev=metrics.previous_evaluation;
    $('#model-comparison').textContent=prev?`上一轮训练 ${prev.train_count} 条，宏平均 F1 ${prev.macro_f1.toFixed(3)}；本轮训练 ${metrics.train_count} 条，宏平均 F1 ${cr['macro avg']['f1-score'].toFixed(3)}。${prev.same_test_ids?'前后使用相同测试评论，整篇笔记从训练侧隔离。':'本轮测试样本与上一轮不同，请结合样本口径阅读。'}${metrics.cv_macro_f1!=null?'训练内部三折分组交叉验证宏平均 F1 '+metrics.cv_macro_f1.toFixed(3)+'。':''}`:'本轮结果来自按笔记分组的测试；更多训练记录会随下一次训练保存。';
  }
  function render(report) {
    state.report=report;state.view=report.dashboard;
    const view=state.view,job=state.job,kpi=view.kpis;
    document.body.dataset.scope=view.scope;document.body.dataset.brand=view.brand;
    $('#brand-title').textContent=view.brand;document.title=`${view.brand} · Brand Pulse 品牌周报`;
    $('#report-description').textContent=`${report.config.primary} 主推品 · 竞品 ${report.config.competitors.join('、')} · ${view.scope==='history'?'全部已采样本':'本期已采样本'}`;
    $('#kpi-volume').textContent=format(kpi.volume);$('#kpi-interactions').textContent=format(kpi.interactions);$('#kpi-positive').textContent=percent(kpi.positive_rate);$('#kpi-risk').textContent=format(kpi.risk_topics);
    $('#metric-coverage').textContent=`${format(kpi.interaction_coverage)} 篇指标完整 · 采集时快照`;
    $('#positive-samples').textContent=`${format(kpi.valid_sentiment_texts)} 条已判定 · ${format(kpi.pending_texts)} 条待复核`;
    $('#positive-progress').style.width=`${(kpi.positive_rate||0)*100}%`;
    $('#risk-caption').textContent='至少3条有效分类评论 · 负向占比≥35%';
    spark('#volume-spark',view.trend.map(d=>d.volume));spark('#interaction-spark',view.trend.map(d=>d.interactions));
    $('#trend-description').textContent=`${view.trend_period[0]} — ${view.trend_period[1]} · 按发布日期聚合`;
    $('#trend-summary').innerHTML=`<strong>${format(kpi.volume)}</strong>篇已识别笔记 <span> · 左轴声量 / 右轴累计互动</span>`;
    trend(view.trend);
    $('#insights').innerHTML=view.insights.slice(0,3).map((item,i)=>`<article class="insight"><span class="insight-number">0${i+1}</span><div><button data-target="${esc(item.target)}"><h3>${esc(item.title)}</h3></button><p>${esc(item.text)}</p></div></article>`).join('');
    renderTopics(view);renderSentiment(view);renderActions(view);renderCollection(job);renderModels(report);
    const palette=['#3474d5','#8aa8d3','#d69d44','#b9c6d6'];
    $('#competitor-bars').innerHTML=view.competitors.map((row,i)=>`<div class="competitor-row"><div class="competitor-label"><i style="background:${palette[i%palette.length]}"></i>${esc(row.brand)}<strong>${percent(row.share)}</strong></div><div class="bar-track"><span style="width:${(row.share||0)*100}%;background:${palette[i%palette.length]}"></span></div><small>${format(row.volume)} 篇 · 累计互动 ${format(row.interactions)}</small></div>`).join('');
    $('#freshness').textContent=`分析 ${localTime(report.generated_at)}${report.stale?' · 有新增数据待更新':''}${state.snapshot?' · 历史快照':''}`;
    $('#week-end').textContent='— '+view.period[1].slice(5).replace('-','.');
    $('#report-stamp').textContent=`${view.brand} · ${view.scope==='history'?'跨期采样':view.period.join(' — ')} · 数据来源 小红书公开内容`;
    const warnings=[];
    if(job.config?.comment_page_limit != null)warnings.push(`评论按每篇前 ${job.config.comment_page_limit} 页主评论与随页回复抽样，保留调整前已采数据；情绪占比仅代表已采样本。`);
    if(!['completed','partial'].includes(job.status))warnings.push(`采集${names[job.status]||job.status}，${format(job.notes_complete)}/${format(job.notes)} 篇完成当前采集目标；当前统计仍受覆盖范围影响。`);
    if(['verification_required','rate_limited','cooldown'].includes(job.status))warnings.push('平台限制会保留断点，页面指标不会用演示值补齐。');
    if(report.stale)warnings.push('新样本已保存，图表包含最新可用笔记；话题与情绪仍以最近一次模型结果为准。');
    const evaluation=report.models.sentiment.metrics?.classification_report?.negative;
    if(evaluation&&(evaluation.recall<.5||evaluation.support<10))warnings.push('负向测试样本较少、召回率偏低，情绪与舆情提示需人工复核。');
    $('#banner').textContent=warnings.join(' ');$('#banner').classList.toggle('hidden',!warnings.length);
    $('#return-current').classList.toggle('hidden',!state.snapshot);
    $('#brand-select').value=view.brand;$('#week-start').value=view.period[0];
    $('#brand-select').disabled=!!state.snapshot;$('#week-start').disabled=!!state.snapshot||view.scope==='history';$$('[data-scope]').forEach(b=>{b.disabled=!!state.snapshot;b.classList.toggle('selected',b.dataset.scope===view.scope);});
  }
  async function archives() {
    if(!state.job)return;
    const rows=await api(`/jobs/${state.job.job_id}/snapshots`);
    $('#archives').innerHTML=rows.slice(0,8).map(row=>`<article class="archive-item"><div><b>${esc(row.primary)} · ${esc(row.period.join(' — '))}</b><p>生成 ${esc(localTime(row.generated_at))} · ${format(row.topic_sample_size)} 条话题样本 · ${format(row.labeled_count)} 条情感标签</p></div><button class="button small" data-snapshot="${esc(row.id)}">查看快照</button></article>`).join('')||'<p class="empty">下一次分析完成后会生成可查看的历史快照。</p>';
  }
  async function refresh(initial=false) {
    if(state.busy)return;state.busy=true;
    $('#workspace').setAttribute('aria-busy','true');
    try {
      const jobs=await api('/jobs');if(!jobs.length)throw Error('尚未创建真实采集任务，请先打开采集工作台。');state.job=jobs[0];
      if(initial){state.week=state.job.config.week_start;state.brand=state.job.config.primary;$('#week-start').value=state.week;$('#brand-select').innerHTML=[state.job.config.primary,...state.job.config.competitors].map((n,i)=>`<option value="${esc(n)}">${esc(n)} · ${i?'竞品':'主推品'}</option>`).join('');}
      const params=new URLSearchParams({scope:state.scope,brand:state.brand,week_start:state.week});if(state.snapshot)params.set('snapshot',state.snapshot);
      const report=await api(`/jobs/${state.job.job_id}/report?${params}`);render(report);
      if(initial||state.archiveStamp!==state.job.analysis_finished_at){await archives();state.archiveStamp=state.job.analysis_finished_at;}
    }catch(error){$('#banner').textContent=error.message;$('#banner').className='banner error';toast(error.message);}finally{state.busy=false;$('#workspace').setAttribute('aria-busy','false');}
  }
  function openEvidence(rows,title) {
    $('#evidence-title').textContent=title;
    $('#evidence-list').innerHTML=rows.map(row=>`<article class="evidence-item"><span class="pill ${row.sentiment||'pending'}">${names[row.sentiment]||'文本证据'}</span><small> ${esc(row.date||'日期缺失')}</small><p>${esc(row.text)}</p><small>笔记 ${esc(row.note_id)}</small><a target="_blank" rel="noopener noreferrer" href="https://www.xiaohongshu.com/explore/${encodeURIComponent(row.note_id)}">打开原文 ↗</a></article>`).join('')||'<p class="empty">当前范围内暂无可展示的文本证据。</p>';
    $('#evidence-dialog').showModal();
  }
  document.addEventListener('click',event=>{
    const topic=event.target.closest('[data-topic]');if(topic&&state.view){const t=state.view.topics.find(t=>t.id===Number(topic.dataset.topic));if(t){$('#topics-dialog').close();openEvidence(t.evidence,t.title);}}
    const target=event.target.closest('[data-target]');if(target)document.getElementById(target.dataset.target)?.scrollIntoView({behavior:'smooth'});
    const snapshot=event.target.closest('[data-snapshot]');if(snapshot){state.snapshot=snapshot.dataset.snapshot;refresh();window.scrollTo({top:0,behavior:'smooth'});}
  });
  $$('.nav-link[href^="#"]').forEach(link=>link.addEventListener('click',()=>{$$('.nav-link').forEach(a=>a.classList.remove('active'));link.classList.add('active');}));
  $$('.close-dialog').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  $$('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}}));
  $('#all-topics').addEventListener('click',()=>$('#topics-dialog').showModal());
  $('#view-comments').addEventListener('click',()=>{if(state.view)openEvidence([...state.view.evidence].sort((a,b)=>(a.sentiment==='negative'?-1:1)-(b.sentiment==='negative'?-1:1)).slice(0,30),'本期评论原声');});
  $('#brand-select').addEventListener('change',event=>{state.brand=event.target.value;refresh();});
  $('#week-start').addEventListener('change',event=>{if(event.target.value){state.week=event.target.value;refresh();}});
  $$('[data-scope]').forEach(button=>button.addEventListener('click',()=>{state.scope=button.dataset.scope;refresh();}));
  $('#return-current').addEventListener('click',()=>{state.snapshot=null;refresh();});$('#refresh').addEventListener('click',()=>refresh());
  $('#actions').addEventListener('change',event=>{if(!event.target.matches('[data-action-id]'))return;const key=$('#actions').dataset.storageKey;let done={};try{done=JSON.parse(localStorage.getItem(key)||'{}');done[event.target.dataset.actionId]=event.target.checked;localStorage.setItem(key,JSON.stringify(done));}catch{toast('当前浏览器未保存行动项，可稍后重试。');}renderActions(state.view);});
  for(const [id,action] of [['pause','pause'],['resume','resume'],['run-topics','analyze'],['train-svm','train']])$('#'+id).addEventListener('click',async()=>{if(!state.job)return;$('#'+id).disabled=true;try{await api(`/jobs/${state.job.job_id}/${action}`,'POST');toast(['analyze','train'].includes(action)?'训练任务已启动，完成后会自动更新可视化结果。':'采集状态已更新。');await refresh();}catch(error){toast(error.message);}finally{$('#'+id).disabled=false;}});
  $('#export').addEventListener('click',()=>{if(!state.report)return;const data={...state.report,dashboard:state.view};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`${state.view.brand}-${state.view.period[0]}-${state.view.scope}-weekly.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('当前分析范围的真实周报已导出。');});
  document.addEventListener('keydown',event=>{if(event.target.matches('input,select,textarea')||document.querySelector('dialog[open]'))return;const id={'1':'overview','2':'topics','3':'competitors','4':'sentiment','5':'models'}[event.key];if(id){event.preventDefault();document.getElementById(id)?.scrollIntoView({behavior:'smooth'});}});
  refresh(true);setInterval(()=>{if(!document.hidden&&!document.querySelector('dialog[open]'))refresh();},15000);
})();
