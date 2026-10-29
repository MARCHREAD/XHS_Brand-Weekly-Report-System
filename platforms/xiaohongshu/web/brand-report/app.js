(() => {
  const toast = document.querySelector('#toast');
  let toastTimer;

  function showToast(message) {
    toast.textContent = message;
    toast.classList.add('is-visible');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 3200);
  }

  function downloadReport() {
    const report = {
      report: 'XHS Brand Weekly Report',
      brand: 'NEO 咖啡',
      period: '2026-10-12/2026-10-18',
      demo: true,
      kpis: { volume: 12480, interactions: 186400, positive_rate: 0.724, risk_topics: 6 },
      note: '演示数据；接入 BrandWeeklySnapshot 后由真实周报快照替换。',
    };
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `neo-coffee-weekly-report-${report.period.replaceAll('/', '-')}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
    showToast('周报 JSON 已导出，可交给分析任务继续生成 PDF。');
  }

  function setActiveSection(id) {
    document.querySelectorAll('.nav-item[data-section]').forEach((item) => {
      item.classList.toggle('is-active', item.dataset.section === id);
    });
  }

  document.querySelectorAll('.nav-item[data-section]').forEach((item) => {
    item.addEventListener('click', () => {
      if (item.dataset.section !== 'collector') setActiveSection(item.dataset.section);
    });
  });

  document.querySelectorAll('[data-scroll]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = document.querySelector(button.dataset.scroll);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  document.querySelector('#export-button')?.addEventListener('click', downloadReport);
  document.querySelector('#refresh-button')?.addEventListener('click', async (event) => {
    const button = event.currentTarget;
    button.classList.add('is-loading');
    try {
      const response = await fetch('/v1/xhs/runtime', { headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error('runtime unavailable');
      const runtime = await response.json();
      const workerCount = runtime?.workers ?? runtime?.worker_count;
      showToast(workerCount ? `采集链路已刷新 · Worker ${workerCount}` : '采集链路已刷新，当前展示周报快照。');
    } catch {
      showToast('当前展示的是离线演示快照，接入采集服务后可刷新实时状态。');
    } finally {
      window.setTimeout(() => button.classList.remove('is-loading'), 350);
    }
  });

  document.querySelector('#week-select')?.addEventListener('change', (event) => {
    const week = event.target.value;
    const message = week === '42' ? '已切换到本周报告。' : `已切换到第 ${week} 周快照，趋势图将由真实数据适配器更新。`;
    showToast(message);
  });

  document.querySelector('#add-action')?.addEventListener('click', () => showToast('行动项编辑器将在接入任务与负责人数据后开放。'));
  document.querySelector('#archive-button')?.addEventListener('click', () => showToast('归档页已预留，将按品牌与周次加载历史快照。'));
  document.querySelector('#workspace-button')?.addEventListener('click', () => showToast('工作区切换已预留，可在配置中心新增品牌。'));

  document.addEventListener('keydown', (event) => {
    if (event.target.matches('input, select, textarea')) return;
    const section = { '1': 'overview', '2': 'topics', '3': 'competitors', '4': 'sentiment', '5': 'archive' }[event.key];
    if (section) {
      event.preventDefault();
      const target = document.querySelector(`#${section}`);
      setActiveSection(section);
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
})();
