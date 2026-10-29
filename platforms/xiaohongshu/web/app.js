"use strict";

const state = {
  response: null,
  data: null,
  durationMs: 0,
  view: "cards",
  health: null,
  lastFocusedCard: null,
  job: null,
  trace: [],
  activeJobId: null,
  qrLoginId: null,
  qrPollTimer: null,
  qrPollBusy: false,
  sessionStatus: null,
  pgySessionStatus: null,
  pgyFilterOptions: null,
  resultType: "generic",
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const collectorForm = $("#collector-form");
const endpointForm = $("#endpoint-form");
const pgyEndpointForm = $("#pgy-endpoint-form");
const resultTitle = $("#result-title");
const responseMeta = $("#response-meta");
const emptyState = $("#empty-state");
const loadingGrid = $("#loading-grid");
const noteGrid = $("#note-grid");
const traceView = $("#trace-view");
const genericResult = $("#generic-result");
const jsonView = $("#json-view");
const copyButton = $("#copy-json");
const csvButton = $("#export-csv");
const toast = $("#toast");
const jobProgress = $("#job-progress");
const sessionDialog = $("#session-dialog");
const pgyDialog = $("#pgy-dialog");
const officialVerificationLink = $("#official-verification-link");
const smsVerificationForm = $("#sms-verification-form");
const smsVerificationCode = $("#sms-verification-code");
const smsVerificationError = $("#sms-verification-error");

const endpointDefinitions = {
  search: {
    method: "GET",
    path: "/v1/xhs/search/notes",
    fields: [
      { name: "keyword", label: "关键词", value: "咖啡", required: true },
      { name: "pages", label: "要抓取多少页", type: "number", value: 1, min: 1, required: true },
      { name: "sort", label: "排序", type: "select", value: "general", options: [["general", "综合"], ["popularity_descending", "最多点赞"], ["time_descending", "最新发布"]] },
    ],
  },
  userSearch: {
    method: "GET",
    path: "/v1/xhs/search/users",
    view: "json",
    fields: [
      { name: "keyword", label: "用户关键词", value: "咖啡", required: true },
      { name: "pages", label: "要抓取多少页", type: "number", value: 1, min: 1, required: true },
    ],
  },
  homefeed: {
    method: "GET",
    path: "/v1/xhs/homefeed",
    fields: [
      { name: "category", label: "频道", value: "homefeed_recommend", required: true },
      { name: "cursor_score", label: "Cursor", value: "" },
      { name: "num", label: "数量", type: "number", value: 20, min: 1, max: 40 },
    ],
  },
  note: {
    method: "GET",
    path: "/v1/xhs/notes/{note_id}",
    fields: [
      { name: "note_id", label: "Note ID", value: "", required: true, path: true },
      { name: "xsec_token", label: "Xsec Token", value: "", required: true },
      { name: "xsec_source", label: "Xsec Source", value: "pc_search", required: true },
      { name: "use_gpt", label: "GPT 补全", type: "checkbox", value: false },
    ],
  },
  comments: {
    method: "GET",
    path: "/v1/xhs/notes/{note_id}/comments",
    fields: [
      { name: "note_id", label: "Note ID", value: "", required: true, path: true },
      { name: "xsec_token", label: "Xsec Token", value: "", required: true },
      { name: "cursor", label: "Cursor", value: "" },
    ],
  },
  author: {
    method: "GET",
    path: "/v1/xhs/users/{user_id}",
    fields: [
      { name: "user_id", label: "User ID", value: "", required: true, path: true },
      { name: "xsec_token", label: "Xsec Token", value: "" },
      { name: "xsec_source", label: "Xsec Source", value: "pc_search" },
    ],
  },
  authorNotes: {
    method: "GET",
    path: "/v1/xhs/users/{user_id}/notes",
    fields: [
      { name: "user_id", label: "User ID", value: "", required: true, path: true },
      { name: "xsec_token", label: "Xsec Token", value: "", required: true },
      { name: "xsec_source", label: "Xsec Source", value: "pc_search", required: true },
      { name: "cursor", label: "Cursor", value: "" },
      { name: "num", label: "数量", type: "number", value: 30, min: 1, max: 30 },
    ],
  },
};

const pgyEndpointDefinitions = {
  noteDetail: {
    method: "POST",
    path: "/v1/xhs/pgy/get_note_detail",
    view: "cards",
    fields: [
      {
        name: "note_url",
        label: "完整笔记链接",
        value: "",
        type: "url",
        placeholder: "粘贴包含 xsec_token 与 xsec_source 的完整链接",
        required: true,
      },
    ],
  },
  bloggerDetail: {
    method: "POST",
    path: "/v1/xhs/pgy/get_blogger_detail",
    view: "cards",
    fields: [
      { name: "user_id", label: "博主 User ID", value: "5c668b3e0000000012021605", required: true },
      { name: "business", label: "笔记口径", type: "select", numeric: true, value: "0", options: [["0", "日常笔记"], ["1", "合作笔记"]] },
      { name: "increase_type", label: "粉丝曲线", type: "select", numeric: true, value: "1", options: [["1", "粉丝总量"], ["2", "每日新增"]] },
      { name: "date_type", label: "时间范围", type: "select", numeric: true, value: "1", options: [["1", "近 30 日"], ["2", "近 60 日"]] },
    ],
  },
  similar: {
    method: "POST",
    path: "/v1/xhs/pgy/get_blogger_similar",
    view: "cards",
    fields: [
      { name: "user_id", label: "目标博主 User ID", value: "5c668b3e0000000012021605", required: true },
      { name: "pages", label: "要抓取多少页", type: "number", value: 1, min: 1, max: 250, required: true },
    ],
  },
  square: {
    method: "POST",
    path: "/v1/xhs/pgy/get_blogger_square",
    customForm: "square",
    view: "cards",
  },
  filterOptions: {
    method: "GET",
    path: "/v1/xhs/pgy/get_blogger_filter_options",
    fields: [],
  },
};

const pgySortOptions = [
  ["comprehensiverank", "智能排序"], ["fansCount", "粉丝数"], ["price", "全部报价"],
  ["clickNum", "阅读中位数-日常"], ["mEngagementNum", "互动中位数-日常"],
  ["accumCommonImpMedinNum30d", "曝光中位数-日常"], ["accumPicCommonImpMedinNum30d", "图文曝光中位数-日常"],
  ["accumVideoCommonImpMedinNum30d", "视频曝光中位数-日常"], ["pictureClickMidNum", "图文阅读中位数-日常"],
  ["videoClickMidNum", "视频阅读中位数-日常"], ["pictureInterMidNum", "图文互动中位数-日常"],
  ["videoInterMidNum", "视频互动中位数-日常"], ["thousandLikePercent30", "千赞笔记比例"],
  ["pictureThousandLikePercent30", "图文千赞比例"], ["videoThousandLikePercent30", "视频千赞比例"],
  ["hundredLikePercent30", "百赞笔记比例"], ["pictureHundredLikePercent30", "图文百赞比例"],
  ["videoHundredLikePercent30", "视频百赞比例"], ["videoFinishRate", "视频完播率"],
  ["accumCoopImpMedinNum30d", "曝光中位数-合作"], ["readMidCoop30", "阅读中位数-合作"],
  ["interMidCoop30", "互动中位数-合作"], ["mCpuvNum30d", "外溢进店中位数-合作"],
  ["picturePrice", "图文报价"], ["videoPrice", "视频报价"], ["pictureReadCost", "图文预估阅读单价"],
  ["videoReadCost", "视频预估阅读单价"], ["inviteReply48hNumRatio", "邀约48h回复率"],
  ["fans30GrowthRate", "粉丝量变化幅度"], ["fansActiveIn28dLv", "活跃粉丝占比"],
  ["fansEngageNum30dLv", "互动粉丝占比"], ["kliveCnt30d", "近30天直播场次"],
  ["avgLiveViewerNum", "场均观播人数"], ["avgAgmv90d", "场均销售额"],
];

function pgyOptionsMarkup(options, selected = "") {
  return options.map(([value, label]) => `<option value="${value}"${String(value) === String(selected) ? " selected" : ""}>${label}</option>`).join("");
}

function pgySelectMarkup(path, label, options, selected = "") {
  return `<label class="pgy-filter-control"><span>${label}</span><select data-path="${path}">${pgyOptionsMarkup(options, selected)}</select></label>`;
}

function pgyRangeMarkup(path, label, suffix = "") {
  return `<label class="pgy-filter-control pgy-range-control"><span>${label}</span><span class="pgy-range-inputs"><input type="number" data-path="${path}.min" placeholder="最小值" inputmode="decimal"><i>至</i><input type="number" data-path="${path}.max" placeholder="最大值${suffix}" inputmode="decimal"></span></label>`;
}

function pgyToggleMarkup(path, label) {
  return `<label class="pgy-filter-check"><input type="checkbox" data-path="${path}" data-boolean="true"><span class="check-box" aria-hidden="true"></span><span>${label}</span></label>`;
}

function pgyPickerMarkup(id, label) {
  return `<div class="pgy-filter-control"><span>${label}</span><details class="pgy-multi-picker" id="${id}"><summary>不限</summary><div class="pgy-picker-panel"><input class="pgy-picker-search" type="search" placeholder="搜索选项" aria-label="搜索${label}"><div class="pgy-picker-options"></div></div></details></div>`;
}

function renderPgySquareFilters(container) {
  container.innerHTML = `
    <div class="pgy-square-search">
      <label class="pgy-filter-control pgy-keyword-control"><span>搜索词</span><input type="search" data-path="keyword" value="" placeholder="不填则只按条件筛选"></label>
      ${pgySelectMarkup("search_type", "搜索方式", [["1", "搜笔记"], ["0", "搜昵称"]], "1")}
      ${pgySelectMarkup("column", "排序指标", pgySortOptions, "comprehensiverank")}
      ${pgySelectMarkup("sort", "方向", [["desc", "降序"], ["asc", "升序"]], "desc")}
      <label class="pgy-filter-control"><span>要抓取多少页</span><input type="number" data-path="pages" data-number="true" value="1" min="1" max="250"></label>
    </div>
    <div class="pgy-filter-loading" id="pgy-filter-loading">正在加载蒲公英动态筛选字典…</div>
    <section class="pgy-filter-section">
      <header><strong>合作目标</strong><span>营销目标与相似博主</span></header>
      <div class="pgy-filter-row pgy-filter-grid">
        ${pgySelectMarkup("goal.market_target", "营销目标", [["", "不限"]])}
        <label class="pgy-filter-control"><span>相似博主 ID</span><input type="text" data-path="similar_user_id" placeholder="User ID"></label>
        <label class="pgy-filter-control"><span>相似博主昵称</span><input type="text" data-path="similar_word" placeholder="仅用于回显"></label>
        <label class="pgy-filter-control"><span>品牌方 User ID</span><input type="text" data-path="brand_user_id" placeholder="可不填"></label>
      </div>
    </section>
    <section class="pgy-filter-section">
      <header><strong>匹配度</strong><span>博主与粉丝画像</span></header>
      <div class="pgy-filter-row">
        <div class="pgy-filter-label">博主类目</div>
        <div class="pgy-choice-grid" id="pgy-content-tags"></div>
      </div>
      <div class="pgy-filter-row pgy-filter-grid pgy-dynamic-grid">
        ${pgyPickerMarkup("pgy-content-tag-detail", "博主细分类目")}
        ${pgyPickerMarkup("pgy-personal-tags", "博主人设")}
        ${pgyPickerMarkup("pgy-feature-tags", "擅长内容")}
        ${pgyPickerMarkup("pgy-blogger-location", "博主地域")}
        ${pgyPickerMarkup("pgy-audience20", "二十大人群")}
        ${pgyPickerMarkup("pgy-industry-crowd", "行业特色画像")}
        ${pgyPickerMarkup("pgy-consumer-behavior", "预估消费行为")}
        ${pgyPickerMarkup("pgy-note-scene", "笔记类目")}
      </div>
      <div class="pgy-filter-row pgy-filter-grid">
        ${pgySelectMarkup("blogger.gender", "博主性别", [["", "不限"], ["男", "男"], ["女", "女"]])}
        ${pgySelectMarkup("blogger.signed", "签约情况", [["", "不限"], ["0", "个人博主"], ["1", "机构博主"]])}
        ${pgyPickerMarkup("pgy-content-theme", "内容题材")}
        ${pgyRangeMarkup("fans.count", "粉丝量")}
        ${pgySelectMarkup("fans.age", "粉丝年龄", [["", "不限"], ["1", "<18 占比高"], ["2", "18~24 占比高"], ["3", "25~34 占比高"], ["4", "35~44 占比高"], ["5", ">44 占比高"]])}
        ${pgySelectMarkup("fans.gender", "粉丝性别", [["", "不限"], ["1", "男性占比高"], ["2", "女性占比高"]])}
        ${pgyPickerMarkup("pgy-fans-location", "粉丝地域")}
        ${pgySelectMarkup("fans.marital_status", "婚恋状态", [["", "不限"], ["0", "未婚"], ["1", "已婚"]])}
        ${pgySelectMarkup("fans.consumption_level", "消费水平", [["", "不限"], ["0", "低消费"], ["1", "中消费"], ["2", "高消费"]])}
      </div>
      <details class="pgy-filter-more">
        <summary>更多粉丝设备与母婴筛选</summary>
        <div class="pgy-filter-row">
          <div class="pgy-filter-label">母婴阶段</div>
          <div class="pgy-choice-grid">${[[0,"备孕"],[2,"0-6月"],[3,"7-12月"],[4,"1-3岁"],[5,"4-6岁"],[6,"7-12岁"],[7,"孕早期"],[8,"孕晚期"]].map(([v,l])=>pgyToggleMarkup("fans.child_age",l).replace('data-boolean="true"',`value="${v}" data-array="true" data-number="true"`)).join("")}</div>
        </div>
        <div class="pgy-filter-row">
          <div class="pgy-filter-label">手机价格</div>
          <div class="pgy-choice-grid">${["0-999","1000-1999","2000-2999","3000-3999","4000-4999","5000-5999","6000-6999","7000-7999","8000+"].map(v=>pgyToggleMarkup("fans.device_price",v).replace('data-boolean="true"',`value="${v}" data-array="true"`)).join("")}</div>
        </div>
        <div class="pgy-filter-row">
          <div class="pgy-filter-label">手机品牌</div>
          <div class="pgy-choice-grid">${["苹果","华为","OPPO","VIVO","荣耀","小米","一加","魅族","中兴","联想"].map(v=>pgyToggleMarkup("fans.device_brand",v).replace('data-boolean="true"',`value="${v}" data-array="true"`)).join("")}</div>
        </div>
      </details>
    </section>
    <section class="pgy-filter-section">
      <header><strong>数据表现</strong><span>日常、合作与直播指标</span></header>
      <div class="pgy-filter-subtitle">日常笔记</div>
      <div class="pgy-filter-row pgy-filter-grid">
        ${pgyRangeMarkup("note.imp_median", "曝光中位数")}
        ${pgyRangeMarkup("note.read_median", "阅读中位数")}
        ${pgyRangeMarkup("note.inter_median", "互动中位数")}
        ${pgyRangeMarkup("note.thousand_like_percent", "千赞笔记比例", "%")}
        ${pgySelectMarkup("note.note_type", "笔记类型", [["", "不限"], ["1", "图文为主"], ["2", "视频为主"]])}
      </div>
      <div class="pgy-filter-subtitle">合作笔记</div>
      <div class="pgy-filter-row pgy-filter-grid">
        ${pgyRangeMarkup("coop.pic_price", "图文报价")}
        ${pgyRangeMarkup("coop.video_price", "视频报价")}
        ${pgyRangeMarkup("coop.order_count", "合作订单数")}
        ${pgyRangeMarkup("coop.reply_48h_ratio", "48h 回复率", "%")}
        ${pgyRangeMarkup("coop.imp_median", "合作曝光中位数")}
        ${pgyRangeMarkup("coop.read_median", "合作阅读中位数")}
        ${pgyRangeMarkup("coop.inter_median", "合作互动中位数")}
        ${pgyRangeMarkup("coop.cpuv", "CPUV")}
        ${pgyRangeMarkup("coop.estimate_cpuv", "外溢进店单价")}
        ${pgyRangeMarkup("coop.pic_cpm", "图文预估 CPM")}
        ${pgyRangeMarkup("coop.video_cpm", "视频预估 CPM")}
        ${pgyRangeMarkup("coop.pic_read_price", "图文阅读单价")}
        ${pgyRangeMarkup("coop.video_read_price", "视频阅读单价")}
        ${pgyRangeMarkup("coop.pic_engage_cost", "图文互动单价")}
        ${pgyRangeMarkup("coop.video_engage_cost", "视频互动单价")}
        ${pgySelectMarkup("coop.industry", "近期合作行业", [["", "不限"], ...["美妆个护","食品饮料","母婴","3c及电器","日用百货","服装配饰","互联网","生活服务","家居建材","汽车"].map(v=>[v,v])])}
        <label class="pgy-filter-control"><span>近期合作品牌 ID</span><input type="text" data-path="coop.brand_ids" data-array-text="true" placeholder="多个 ID 用逗号分隔"></label>
        ${pgyToggleMarkup("coop.exclude_brands", "排除这些品牌")}
      </div>
      <div class="pgy-filter-subtitle">直播数据</div>
      <div class="pgy-filter-row pgy-filter-grid">
        ${pgyRangeMarkup("live.live_count", "近 30 天直播场次")}
        ${pgyRangeMarkup("live.avg_viewer", "场均观播人数")}
        ${pgyRangeMarkup("live.avg_gmv", "场均销售额")}
      </div>
    </section>
    <section class="pgy-filter-section pgy-flag-section">
      <header><strong>平台推荐</strong><span>精选与行业推荐</span></header>
      <div class="pgy-filter-row pgy-choice-grid">
        ${pgyToggleMarkup("flags.is_star", "明星")}
        ${pgyToggleMarkup("flags.high_quality", "优质博主")}
        ${pgyToggleMarkup("flags.new_high_quality", "新锐博主")}
        ${pgyToggleMarkup("flags.note_and_live", "笔记+直播均可合作")}
        ${pgyToggleMarkup("flags.filter_intention", "意向行业匹配")}
      </div>
      <div class="pgy-filter-row pgy-filter-grid">
        ${pgySelectMarkup("flags.industry_first", "行业一级", [["", "不限"]])}
        ${pgySelectMarkup("flags.industry_second", "行业二级", [["", "不限"]])}
        ${pgyPickerMarkup("pgy-activities", "热门活动")}
      </div>
    </section>
    <section class="pgy-filter-section pgy-flag-section">
      <header><strong>常规剔除</strong><span>快速排除低质量或重复触达</span></header>
      <div class="pgy-filter-row pgy-choice-grid">
        ${pgyToggleMarkup("flags.exclude_low_active", "剔除低活博主")}
        ${pgyToggleMarkup("flags.exclude_fans_down", "剔除掉粉博主")}
        ${pgyToggleMarkup("flags.exclude_cooperated", "剔除已合作博主")}
        ${pgyToggleMarkup("flags.exclude_invited", "剔除已邀约博主")}
      </div>
    </section>
    <details class="pgy-advanced-json">
      <summary>高级 JSON 补充</summary>
      <label class="field"><span>提交前与上面控件生成的请求体深度合并</span><textarea name="advanced_body" spellcheck="false">{}</textarea></label>
    </details>`;
}

function pgyNodeLabel(node) {
  return String(node?.label ?? node?.name ?? node?.tagName ?? node?.taxonomy1Tag ?? "").trim();
}

function pgyNodeChildren(node) {
  const children = node?.children ?? node?.subTagList;
  return Array.isArray(children) ? children : [];
}

function flattenPgyTree(nodes, { leavesOnly = false, fullPath = false, valueFrom = null } = {}, parents = []) {
  const result = [];
  (Array.isArray(nodes) ? nodes : []).forEach((node) => {
    if (!node || typeof node !== "object") return;
    const label = pgyNodeLabel(node);
    if (!label) return;
    const path = [...parents, label];
    const children = pgyNodeChildren(node);
    if (!leavesOnly || !children.length) {
      const rawValue = valueFrom ? valueFrom(node, path) : (node.value ?? node.code ?? node.tagName ?? label);
      if (rawValue !== undefined && rawValue !== null && rawValue !== "") {
        result.push({ label: path.join(" / "), value: fullPath ? path.join(" ") : String(rawValue) });
      }
    }
    result.push(...flattenPgyTree(children, { leavesOnly, fullPath, valueFrom }, path));
  });
  return result;
}

function uniquePgyOptions(options) {
  const seen = new Set();
  return options.filter((option) => {
    const key = `${option.label}\u0000${option.value}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function updatePgyPickerSummary(details) {
  const count = $$('input[type="checkbox"]:checked', details).length;
  $("summary", details).textContent = count ? `已选 ${count} 项` : "不限";
}

function populatePgyPicker(id, options, path, { number = false } = {}) {
  const details = $(`#${id}`);
  if (!details) return;
  const panel = $(".pgy-picker-options", details);
  panel.replaceChildren();
  uniquePgyOptions(options).forEach((option) => {
    const label = createElement("label", "pgy-picker-option");
    const input = createElement("input");
    input.type = "checkbox";
    input.value = option.value;
    input.dataset.path = path;
    input.dataset.array = "true";
    if (number) input.dataset.number = "true";
    label.title = option.label;
    label.append(input, createElement("span", "", option.label));
    panel.append(label);
  });
  details.addEventListener("change", () => updatePgyPickerSummary(details));
  const search = $(".pgy-picker-search", details);
  search.addEventListener("input", () => {
    const query = search.value.trim().toLowerCase();
    $$(".pgy-picker-option", details).forEach((option) => {
      option.hidden = Boolean(query) && !option.textContent.toLowerCase().includes(query);
    });
  });
}

function populatePgyContentTags(contentTags) {
  const container = $("#pgy-content-tags");
  if (!container) return;
  container.replaceChildren();
  const detailed = [];
  (Array.isArray(contentTags) ? contentTags : []).forEach((item) => {
    const first = String(item?.taxonomy1Tag || "").trim();
    if (!first) return;
    const label = createElement("label", "pgy-filter-check pgy-choice-pill");
    const input = createElement("input");
    input.type = "checkbox";
    input.value = first;
    input.dataset.path = "blogger.content_tag";
    input.dataset.array = "true";
    label.append(input, createElement("span", "", first));
    container.append(label);
    (item.taxonomy2Tags || []).forEach((second) => detailed.push({ label: `${first} / ${second}`, value: second }));
  });
  populatePgyPicker("pgy-content-tag-detail", detailed, "blogger.content_tag");
}

function setPgySelectOptions(path, options, selected = "") {
  const select = $(`[data-path="${path}"]`, pgyEndpointForm);
  if (!select) return;
  select.replaceChildren();
  [["", "不限"], ...options].forEach(([value, label]) => {
    const option = createElement("option", "", label);
    option.value = value;
    option.selected = String(value) === String(selected);
    select.append(option);
  });
}

async function hydratePgySquareFilters() {
  const status = $("#pgy-filter-loading");
  try {
    if (!state.pgyFilterOptions) {
      const payload = await requestApi("/v1/xhs/pgy/get_blogger_filter_options");
      state.pgyFilterOptions = payload.data?.data || {};
    }
    if (!status.isConnected) return;
    const options = state.pgyFilterOptions;
    populatePgyContentTags(options.contentTags);

    populatePgyPicker(
      "pgy-personal-tags",
      flattenPgyTree(options.personalTagsV2, { valueFrom: (node) => node.tagName }),
      "blogger.personal_tags",
    );
    const featureOptions = [];
    (options.featureTags || []).forEach((item) => {
      if (item.taxonomy1Tag) featureOptions.push({ label: item.taxonomy1Tag, value: item.taxonomy1Tag });
      (item.taxonomy2Tags || []).forEach((value) => featureOptions.push({ label: `${item.taxonomy1Tag} / ${value}`, value }));
    });
    populatePgyPicker("pgy-feature-tags", featureOptions, "blogger.feature_tags");

    const areaOptions = flattenPgyTree(options.areas).filter((item) => item.value !== "中国");
    const fansAreaOptions = flattenPgyTree(options.fansAreas).filter((item) => item.value !== "中国");
    populatePgyPicker("pgy-blogger-location", areaOptions, "blogger.location");
    populatePgyPicker("pgy-fans-location", fansAreaOptions, "fans.location");

    const audienceOptions = [];
    (options.audience20 || []).forEach((item) => {
      const first = pgyNodeLabel(item);
      if (!first) return;
      audienceOptions.push({ label: first, value: first });
      pgyNodeChildren(item).forEach((child) => {
        const second = pgyNodeLabel(child);
        if (second) audienceOptions.push({ label: `${first} / ${second}`, value: `${first} ${first}-${second}` });
      });
    });
    populatePgyPicker("pgy-audience20", audienceOptions, "blogger.audience20");
    populatePgyPicker(
      "pgy-industry-crowd",
      flattenPgyTree(options.automotiveIndustryTag, { leavesOnly: true }),
      "blogger.industry_crowd",
    );
    populatePgyPicker(
      "pgy-consumer-behavior",
      flattenPgyTree(options.consumerBehavior, { fullPath: true }),
      "blogger.consumer_behavior",
    );
    populatePgyPicker(
      "pgy-note-scene",
      flattenPgyTree(options.contentScenes, { fullPath: true }),
      "blogger.note_scene",
    );
    populatePgyPicker(
      "pgy-content-theme",
      (options.contentTheme || []).map((item) => ({ label: pgyNodeLabel(item), value: pgyNodeLabel(item) })),
      "blogger.content_theme",
    );
    populatePgyPicker(
      "pgy-activities",
      (options.activities || []).map((item) => ({ label: item.activityName || item.name || item.code, value: item.code })),
      "flags.activity_codes",
    );

    const marketOptions = [];
    (options.market || []).forEach((first) => {
      pgyNodeChildren(first).forEach((second) => {
        pgyNodeChildren(second).forEach((leaf) => {
          marketOptions.push({
            label: `${pgyNodeLabel(first)} / ${pgyNodeLabel(second)} / ${pgyNodeLabel(leaf)}`,
            value: String(leaf.type || leaf.value || ""),
          });
        });
      });
    });
    setPgySelectOptions("goal.market_target", marketOptions.map((item) => [item.value, item.label]));

    const industryMap = new Map();
    (options.industryTags || []).forEach((item) => {
      const first = String(item.taxonomy1Tag || "");
      if (first) industryMap.set(first, item.taxonomy2Tags || []);
    });
    setPgySelectOptions("flags.industry_first", [...industryMap.keys()].map((value) => [value, value]));
    const firstSelect = $('[data-path="flags.industry_first"]', pgyEndpointForm);
    const secondSelect = $('[data-path="flags.industry_second"]', pgyEndpointForm);
    const refreshSecondIndustry = () => {
      const second = (industryMap.get(firstSelect.value) || []).map((value) => [value, value]);
      setPgySelectOptions("flags.industry_second", second);
      secondSelect.disabled = !firstSelect.value;
    };
    firstSelect.addEventListener("change", refreshSecondIndustry);
    refreshSecondIndustry();
    status.textContent = "动态筛选字典已加载";
    status.classList.add("is-ready");
  } catch (error) {
    status.textContent = `筛选字典加载失败：${error.message}`;
    status.classList.add("is-error");
  }
}

function setNestedValue(target, path, value, { array = false } = {}) {
  const parts = path.split(".");
  let cursor = target;
  parts.slice(0, -1).forEach((part) => {
    if (!cursor[part] || typeof cursor[part] !== "object" || Array.isArray(cursor[part])) cursor[part] = {};
    cursor = cursor[part];
  });
  const key = parts.at(-1);
  if (array) {
    if (!Array.isArray(cursor[key])) cursor[key] = [];
    if (!cursor[key].some((item) => String(item) === String(value))) cursor[key].push(value);
  } else {
    cursor[key] = value;
  }
}

function mergeObjects(target, source) {
  Object.entries(source || {}).forEach(([key, value]) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      if (!target[key] || typeof target[key] !== "object" || Array.isArray(target[key])) target[key] = {};
      mergeObjects(target[key], value);
    } else {
      target[key] = value;
    }
  });
  return target;
}

function buildPgySquareBody(form) {
  const body = {};
  const numericPaths = new Set([
    "search_type", "pages", "page_num", "page_size", "blogger.signed", "fans.age", "fans.gender",
    "fans.marital_status", "fans.consumption_level", "note.note_type",
  ]);
  $$('[data-path]', form).forEach((input) => {
    const path = input.dataset.path;
    if (input.type === "checkbox") {
      if (!input.checked) return;
      const raw = input.dataset.boolean === "true" ? true : input.value;
      const value = input.dataset.number === "true" ? Number(raw) : raw;
      setNestedValue(body, path, value, { array: input.dataset.array === "true" });
      return;
    }
    const raw = String(input.value || "").trim();
    if (!raw) return;
    if (input.dataset.arrayText === "true") {
      raw.split(/[,，\n]/).map((value) => value.trim()).filter(Boolean).forEach((value) => {
        setNestedValue(body, path, value, { array: true });
      });
      return;
    }
    const value = input.dataset.number === "true" || numericPaths.has(path) || input.type === "number" ? Number(raw) : raw;
    setNestedValue(body, path, value);
  });
  const advanced = String(form.elements.advanced_body?.value || "{}").trim();
  if (advanced && advanced !== "{}") mergeObjects(body, JSON.parse(advanced));
  return body;
}

function updatePgySquareLayout() {
  const pgyMode = !pgyEndpointForm.classList.contains("is-hidden");
  const square = $("#pgy-endpoint-select").value === "square";
  $("#workspace").classList.toggle("is-pgy-square", pgyMode && square);
}

function createElement(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== "") element.textContent = String(text);
  return element;
}

function setChip(id, text, status) {
  const chip = $(id);
  const actionable = ["cookie-status", "pgy-status"].includes(chip.id);
  chip.className = `status-chip is-${status}${actionable ? " status-action" : ""}`;
  chip.replaceChildren(createElement("i"), document.createTextNode(text));
}

async function loadHealth() {
  try {
    const response = await fetch("/health");
    const payload = await response.json();
    if (!response.ok || payload.code !== 0) throw new Error(payload.message || "健康检查失败");
    state.health = payload.data;
    setChip("#api-status", "API 在线", "ok");
    const sessionState = payload.data.session?.state || (payload.data.xhs_cookie_configured ? "unverified" : "missing");
    const sessionChip = {
      valid: ["会话有效 · 自动续期", "ok"],
      degraded: ["会话网络待复查", "pending"],
      unverified: ["会话待验证", "pending"],
      expired: ["会话已失效 · 重新登录", "error"],
      error: ["会话配置异常", "error"],
      missing: ["Cookie 未配置 · 登录", "error"],
    }[sessionState] || ["会话状态未知", "off"];
    setChip("#cookie-status", sessionChip[0], sessionChip[1]);
    const pgyState = payload.data.pgy_session?.state || (payload.data.pgy_cookie_configured ? "unverified" : "missing");
    const pgyChip = {
      valid: ["蒲公英已登录", "ok"],
      degraded: ["蒲公英待复查", "pending"],
      unverified: ["蒲公英待验证", "pending"],
      expired: ["蒲公英已失效", "error"],
      error: ["蒲公英登录失败", "error"],
      missing: ["蒲公英未登录", "off"],
    }[pgyState] || ["蒲公英状态未知", "off"];
    setChip("#pgy-status", pgyChip[0], pgyChip[1]);
    setChip("#worker-status", `Worker ${payload.data.effective_workers}/${payload.data.configured_workers}`, payload.data.effective_workers ? "ok" : "error");
    setChip("#gpt-status", payload.data.openai_configured ? "GPT 已连接" : "GPT 未配置", payload.data.openai_configured ? "ok" : "off");
    const gptInput = collectorForm.elements.use_gpt;
    gptInput.disabled = !payload.data.openai_configured;
    $("#gpt-toggle-row").classList.toggle("is-disabled", !payload.data.openai_configured);
    $("#gpt-toggle-row").title = payload.data.openai_configured ? "" : "配置 OPENAI_API_KEY 后启用";
  } catch (error) {
    setChip("#api-status", "API 离线", "error");
    setChip("#cookie-status", "Cookie 未知", "off");
    setChip("#pgy-status", "蒲公英未知", "off");
    setChip("#worker-status", "Worker 未知", "off");
    setChip("#gpt-status", "GPT 未知", "off");
  }
}

function renderPgySessionStatus(session) {
  state.pgySessionStatus = session;
  const status = session?.state || "missing";
  const labels = {
    valid: "蒲公英会话有效",
    degraded: "网络异常，保留原会话",
    unverified: "Cookie 已读取，等待验证",
    expired: "蒲公英会话已失效",
    error: "蒲公英登录失败",
    missing: "尚未登录蒲公英",
  };
  const dot = $("#pgy-health-dot");
  dot.className = `session-health-dot is-${status}`;
  $("#pgy-health-title").textContent = labels[status] || "蒲公英状态未知";
  const detail = session?.last_error;
  $("#pgy-health-meta").textContent = detail
    ? detail
    : `最近验证 ${formatSessionTime(session?.last_verified_at)}`;
  const stateLine = $("#pgy-session-state");
  stateLine.textContent = status === "valid" ? "登录会话有效，数据接口按账号权限开放" : labels[status];
  stateLine.className = `session-state${status === "valid" ? " is-success" : ["expired", "error"].includes(status) ? " is-error" : ""}`;
}

async function loadPgySessionStatus() {
  try {
    const data = await authRequest("/v1/xhs/pgy/auth/session");
    renderPgySessionStatus(data);
    return data;
  } catch (error) {
    renderPgySessionStatus({ state: "error", last_error: error.message });
    return null;
  }
}

async function verifyPgySession() {
  const button = $("#verify-pgy-session");
  button.disabled = true;
  button.textContent = "验证中…";
  try {
    const data = await authRequest("/v1/xhs/pgy/auth/session/verify", { method: "POST" });
    renderPgySessionStatus(data);
    await loadHealth();
    showToast(data.state === "valid" ? "蒲公英会话验证通过" : "蒲公英会话需要重新登录");
  } catch (error) {
    renderPgySessionStatus({ state: "error", last_error: error.message });
  } finally {
    button.disabled = false;
    button.textContent = "立即验证";
  }
}

async function openPgyDialog() {
  if (!pgyDialog.open) pgyDialog.showModal();
  await loadPgySessionStatus();
  (!$("#pgy-phone-form").hidden ? $("#pgy-phone") : $("#pgy-email")).focus();
}

const pgyPhoneLogin = { loginId: null, expiresAt: 0, resendAt: 0, busy: false, timer: null };

$$('[data-pgy-login]').forEach((button) => {
  button.addEventListener("click", () => {
    if (pgyPhoneLogin.busy || $("#pgy-login-button").disabled) return;
    const phone = button.dataset.pgyLogin === "phone";
    $("#pgy-phone-form").hidden = !phone;
    $("#pgy-login-form").hidden = phone;
    $$('[data-pgy-login]').forEach((item) => {
      const selected = item === button;
      item.classList.toggle("is-active", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    (phone ? $("#pgy-phone") : $("#pgy-email")).focus();
  });
});

function updatePgyPhoneControls() {
  const now = Date.now();
  const seconds = Math.max(0, Math.ceil((pgyPhoneLogin.resendAt - now) / 1000));
  const send = $("#pgy-send-code");
  send.disabled = pgyPhoneLogin.busy || seconds > 0;
  send.textContent = pgyPhoneLogin.busy ? "处理中…" : seconds > 0 ? `${seconds} 秒后可重发` : "发送验证码";
  if (pgyPhoneLogin.loginId && now >= pgyPhoneLogin.expiresAt) {
    pgyPhoneLogin.loginId = null;
    $("#pgy-phone-hint").textContent = "本次登录尝试已过期，请重新发送验证码。";
  }
  $("#pgy-phone-login-button").disabled = pgyPhoneLogin.busy || !pgyPhoneLogin.loginId;
  $("#pgy-phone").readOnly = pgyPhoneLogin.busy;
  if (!pgyPhoneLogin.busy && !seconds && !pgyPhoneLogin.loginId && pgyPhoneLogin.timer) {
    window.clearInterval(pgyPhoneLogin.timer);
    pgyPhoneLogin.timer = null;
  }
}

$("#pgy-phone").addEventListener("input", () => {
  pgyPhoneLogin.loginId = null;
  $("#pgy-phone-code").value = "";
  $("#pgy-phone-hint").textContent = "手机号已改变，请为当前号码重新发送验证码。";
  updatePgyPhoneControls();
});

$("#pgy-send-code").addEventListener("click", async () => {
  const phone = $("#pgy-phone");
  const policy = $("#pgy-phone-policy");
  if (!phone.reportValidity() || !policy.reportValidity()) return;
  if (pgyPhoneLogin.busy || Date.now() < pgyPhoneLogin.resendAt) return;
  pgyPhoneLogin.busy = true;
  pgyPhoneLogin.loginId = null;
  $("#pgy-phone-error").textContent = "";
  $("#pgy-phone-code").value = "";
  updatePgyPhoneControls();
  try {
    const data = await authRequest("/v1/xhs/pgy/auth/phone/code", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone: phone.value.trim(), zone: "86" }),
    });
    pgyPhoneLogin.loginId = data.login_id;
    pgyPhoneLogin.expiresAt = Date.now() + data.expires_in * 1000;
    pgyPhoneLogin.resendAt = Date.now() + data.resend_in * 1000;
    $("#pgy-phone-hint").textContent = `验证码已发送至 ${data.receiver}，请在 ${Math.ceil(data.expires_in / 60)} 分钟内提交。`;
    $("#pgy-phone-code").focus();
  } catch (error) {
    $("#pgy-phone-error").textContent = error.message;
    // Backend also applies the official resend interval after rejected sends.
    pgyPhoneLogin.resendAt = Date.now() + 60000;
  } finally {
    pgyPhoneLogin.busy = false;
    updatePgyPhoneControls();
    if (!pgyPhoneLogin.timer) pgyPhoneLogin.timer = window.setInterval(updatePgyPhoneControls, 1000);
  }
});

$("#pgy-phone-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  updatePgyPhoneControls();
  if (!pgyPhoneLogin.loginId || pgyPhoneLogin.busy) return;
  pgyPhoneLogin.busy = true;
  $("#pgy-phone-error").textContent = "";
  updatePgyPhoneControls();
  try {
    const data = await authRequest("/v1/xhs/pgy/auth/phone", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ login_id: pgyPhoneLogin.loginId, code: $("#pgy-phone-code").value.trim() }),
    });
    pgyPhoneLogin.loginId = null;
    renderPgySessionStatus(data);
    await loadHealth();
    $("#pgy-phone-hint").textContent = "登录成功，会话已保存。";
    showToast("蒲公英登录成功，会话已保存");
  } catch (error) {
    $("#pgy-phone-error").textContent = error.message;
  } finally {
    $("#pgy-phone-code").value = "";
    pgyPhoneLogin.busy = false;
    updatePgyPhoneControls();
  }
});

$("#pgy-login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = $("#pgy-login-button");
  const error = $("#pgy-login-error");
  const email = form.elements.email.value.trim();
  const password = form.elements.password.value;
  button.disabled = true;
  $("span", button).textContent = "登录中…";
  error.textContent = "";
  try {
    const data = await authRequest("/v1/xhs/pgy/auth/email", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    form.elements.password.value = "";
    renderPgySessionStatus(data);
    await loadHealth();
    showToast("蒲公英登录成功，会话已保存");
  } catch (loginError) {
    form.elements.password.value = "";
    error.textContent = loginError.message;
    renderPgySessionStatus({ state: "error", last_error: loginError.message });
  } finally {
    button.disabled = false;
    $("span", button).textContent = "登录并保存会话";
  }
});

$("#pgy-status").addEventListener("click", openPgyDialog);
$("#verify-pgy-session").addEventListener("click", verifyPgySession);
$("#close-pgy-dialog").addEventListener("click", () => pgyDialog.close());

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.setTimeout(() => toast.classList.remove("is-visible"), 2400);
}

function stopQrPolling() {
  if (state.qrPollTimer) window.clearTimeout(state.qrPollTimer);
  state.qrPollTimer = null;
  state.qrPollBusy = false;
}

function setQrState(message, kind = "", countdown = "") {
  const status = $("#session-state");
  status.textContent = message;
  status.className = `session-state${kind ? ` is-${kind}` : ""}`;
  $("#session-countdown").textContent = countdown;
}

function hideSmsVerification() {
  smsVerificationForm.hidden = true;
  smsVerificationError.textContent = "";
}

function formatSessionTime(value) {
  if (!value) return "尚未验证";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "尚未验证" : date.toLocaleString("zh-CN", { hour12: false });
}

function renderSessionStatus(session) {
  state.sessionStatus = session;
  const status = session?.state || "missing";
  const labels = {
    valid: "服务端验证通过",
    degraded: "网络异常，保留原会话",
    unverified: "Cookie 已读取，等待验证",
    expired: "服务端确认会话失效",
    error: "会话配置异常",
    missing: "尚未配置登录 Cookie",
  };
  const dot = $("#session-health-dot");
  dot.className = `session-health-dot is-${status}`;
  $("#session-health-title").textContent = labels[status] || "会话状态未知";
  const sessions = Array.isArray(session?.sessions) ? session.sessions : [];
  const lastVerified = sessions.map((item) => item.last_verified_at).filter(Boolean).sort().at(-1);
  const detail = session?.load_error || sessions.find((item) => item.last_error)?.last_error;
  $("#session-health-meta").textContent = detail
    ? `${session?.active || 0}/${session?.total || 0} 可用 · ${detail}`
    : `${session?.active || 0}/${session?.total || 0} 可用 · 最近验证 ${formatSessionTime(lastVerified)}`;
}

async function authRequest(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.code !== 0) {
    const detail = payload?.detail || payload?.message || `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload.data;
}

async function loadSessionStatus() {
  try {
    const data = await authRequest("/v1/xhs/auth/session");
    renderSessionStatus(data);
    return data;
  } catch (error) {
    renderSessionStatus({ state: "error", active: 0, total: 0, load_error: error.message, sessions: [] });
    return null;
  }
}

async function verifySession() {
  const button = $("#verify-session");
  button.disabled = true;
  button.textContent = "验证中…";
  try {
    const data = await authRequest("/v1/xhs/auth/session/verify", { method: "POST" });
    renderSessionStatus(data);
    await loadHealth();
    if (data.state === "valid") {
      setQrState("当前会话有效，后台会继续定期验证", "success", "无需保持浏览器登录");
      showToast("小红书会话验证通过");
    } else if (data.state === "expired") {
      setQrState("当前会话已失效", "error", "请生成二维码重新登录");
    } else if (data.state === "missing") {
      setQrState("尚未配置登录 Cookie", "", "请生成二维码完成一次账号确认");
    } else if (data.state === "unverified") {
      setQrState("Cookie 已读取，等待服务端确认", "", "后台将按计划再次检查");
    } else if (data.state === "degraded") {
      setQrState("网络异常，原会话仍保留", "", "后台将按计划再次检查");
    } else {
      setQrState("会话状态需要复查", "", "可稍后再次验证或重新登录");
    }
  } catch (error) {
    setQrState("会话验证失败", "error", error.message);
  } finally {
    button.disabled = false;
    button.textContent = "立即验证";
  }
}

async function pollQrLogin() {
  if (!state.qrLoginId || state.qrPollBusy || !sessionDialog.open) return;
  state.qrPollBusy = true;
  try {
    const data = await authRequest(`/v1/xhs/auth/qrcode/${encodeURIComponent(state.qrLoginId)}`);
    const seconds = Math.max(0, Number(data.expires_in || 0));
    if (data.state === "authenticated") {
      stopQrPolling();
      officialVerificationLink.hidden = true;
      hideSmsVerification();
      setQrState("登录成功，采集 Worker 已切换", "success", "会话已保存到本机");
      await loadHealth();
      await loadSessionStatus();
      showToast("小红书采集会话已更新");
      window.setTimeout(() => { if (sessionDialog.open) sessionDialog.close(); }, 900);
      return;
    }
    if (data.state === "expired") {
      stopQrPolling();
      officialVerificationLink.hidden = true;
      hideSmsVerification();
      setQrState("二维码已过期", "error", "请重新生成二维码");
      $("#start-qr-login").disabled = false;
      $("#start-qr-login span").textContent = "重新生成二维码";
      return;
    }
    if (["verification_waiting_scan", "verification_scanned"].includes(data.state)) {
      officialVerificationLink.hidden = true;
      hideSmsVerification();
      if (data.qr_image) $("#login-qr").src = data.qr_image;
      $("#login-qr").hidden = false;
      $("#qr-placeholder").hidden = true;
      $("#login-qr").alt = "使用同一小红书 App 账号扫描的二次验证二维码";
      const verificationLabel = data.verification_type ? ` · 验证类型 ${data.verification_type}` : "";
      setQrState(
        data.state === "verification_scanned" ? "验证已扫码，请在 App 中确认" : "需要再次扫码验证，请扫描这张新二维码",
        "", `${seconds} 秒后过期 · 使用刚才的同一账号${verificationLabel}`,
      );
      state.qrPollTimer = window.setTimeout(pollQrLogin, 2000);
      return;
    }
    if (data.state === "sms_code_required") {
      officialVerificationLink.hidden = true;
      $("#login-qr").hidden = true;
      $("#qr-placeholder").hidden = false;
      $("#qr-frame").setAttribute("aria-busy", "false");
      smsVerificationForm.hidden = false;
      $("#sms-receiver").textContent = data.receiver || "账号绑定手机";
      const resendIn = Math.max(0, Number(data.resend_in || 0));
      $("#resend-sms-code").disabled = resendIn > 0;
      $("#resend-sms-code").textContent = resendIn > 0 ? `${resendIn} 秒后可重发` : "重新发送";
      setQrState("请输入短信验证码", "", `${seconds} 秒后登录尝试过期 · 验证类型 120`);
      $("#start-qr-login").disabled = true;
      $("#start-qr-login span").textContent = "等待短信验证";
      state.qrPollTimer = window.setTimeout(pollQrLogin, 1000);
      return;
    }
    if (data.state === "verification_required") {
      hideSmsVerification();
      $("#login-qr").hidden = true;
      $("#qr-placeholder").hidden = false;
      $("#qr-frame").setAttribute("aria-busy", "false");
      officialVerificationLink.href = data.verification_url;
      officialVerificationLink.hidden = !data.verification_url;
      setQrState(
        `需要在小红书官方页面验证（类型 ${data.verification_type || "未知"}）`,
        "error",
        data.verification_url ? "打开官方验证页完成操作，本页会自动继续检查" : data.message,
      );
      $("#start-qr-login").disabled = true;
      $("#start-qr-login span").textContent = "等待官方验证完成";
      state.qrPollTimer = window.setTimeout(pollQrLogin, 2000);
      return;
    }
    if (["verification_cancelled", "verification_failed"].includes(data.state)) {
      stopQrPolling();
      officialVerificationLink.hidden = true;
      hideSmsVerification();
      const messages = {
        verification_cancelled: "你已取消本次验证",
        verification_failed: "本次验证未通过",
      };
      setQrState(messages[data.state], "error", data.message || "可重新生成登录二维码");
      $("#start-qr-login").disabled = false;
      $("#start-qr-login span").textContent = "重新生成二维码";
      return;
    }
    setQrState(data.state === "scanned" ? "已扫码，请在 App 中确认" : "等待小红书 App 扫码", "", `${seconds} 秒后过期`);
    state.qrPollTimer = window.setTimeout(pollQrLogin, 2000);
  } catch (error) {
    stopQrPolling();
    setQrState("会话轮询失败", "error", error.message);
    $("#start-qr-login").disabled = false;
    $("#start-qr-login span").textContent = "重新生成二维码";
  } finally {
    state.qrPollBusy = false;
  }
}

async function startQrLogin() {
  stopQrPolling();
  officialVerificationLink.hidden = true;
  hideSmsVerification();
  const button = $("#start-qr-login");
  const qr = $("#login-qr");
  qr.alt = "使用小红书 App 扫描的登录二维码";
  const placeholder = $("#qr-placeholder");
  button.disabled = true;
  $("span", button).textContent = "正在生成…";
  qr.hidden = true;
  placeholder.hidden = false;
  $("#qr-frame").setAttribute("aria-busy", "true");
  setQrState("正在建立匿名设备会话", "", "");
  try {
    const data = await authRequest("/v1/xhs/auth/qrcode", { method: "POST" });
    state.qrLoginId = data.login_id;
    qr.src = data.qr_image;
    qr.hidden = false;
    placeholder.hidden = true;
    $("#qr-frame").setAttribute("aria-busy", "false");
    $("span", button).textContent = "二维码有效期内请完成确认";
    setQrState("等待小红书 App 扫码", "", `${data.expires_in} 秒后过期`);
    state.qrPollTimer = window.setTimeout(pollQrLogin, 2000);
  } catch (error) {
    button.disabled = false;
    $("span", button).textContent = "重新生成二维码";
    $("#qr-frame").setAttribute("aria-busy", "false");
    setQrState("二维码生成失败", "error", error.message);
  }
}

smsVerificationForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.qrLoginId) return;
  const code = smsVerificationCode.value.trim();
  if (!/^\d{6}$/.test(code)) {
    smsVerificationError.textContent = "请输入 6 位数字验证码";
    return;
  }
  const button = $("#submit-sms-code");
  button.disabled = true;
  button.textContent = "验证中…";
  smsVerificationError.textContent = "";
  try {
    await authRequest(`/v1/xhs/auth/qrcode/${encodeURIComponent(state.qrLoginId)}/sms`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    smsVerificationCode.value = "";
    hideSmsVerification();
    setQrState("短信验证通过，正在继续登录", "success", "");
    state.qrPollTimer = window.setTimeout(pollQrLogin, 100);
  } catch (error) {
    smsVerificationError.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "验证并继续";
  }
});

$("#resend-sms-code").addEventListener("click", async () => {
  if (!state.qrLoginId) return;
  const button = $("#resend-sms-code");
  button.disabled = true;
  smsVerificationError.textContent = "";
  try {
    await authRequest(`/v1/xhs/auth/qrcode/${encodeURIComponent(state.qrLoginId)}/sms/resend`, { method: "POST" });
    showToast("短信验证码已重新发送");
    state.qrPollTimer = window.setTimeout(pollQrLogin, 100);
  } catch (error) {
    smsVerificationError.textContent = error.message;
    button.disabled = false;
  }
});

async function openSessionDialog() {
  if (!sessionDialog.open) sessionDialog.showModal();
  $("#verify-session").focus();
  const session = await loadSessionStatus();
  if (session?.state === "valid") {
    setQrState("当前会话有效，后台会继续定期验证", "success", "需要更换账号时可生成新二维码");
  } else if (session?.state === "expired") {
    setQrState("当前会话已失效", "error", "请生成二维码重新登录");
  }
}

$("#cookie-status").addEventListener("click", openSessionDialog);
$("#verify-session").addEventListener("click", verifySession);
$("#start-qr-login").addEventListener("click", startQrLogin);
$("#close-session-dialog").addEventListener("click", () => sessionDialog.close());
sessionDialog.addEventListener("close", () => {
  stopQrPolling();
  state.qrLoginId = null;
});

function setLoading(loading, button) {
  if (button) {
    button.disabled = loading;
    $("span", button).textContent = loading ? "请求中…" : button.dataset.defaultLabel;
  }
  emptyState.classList.add("is-hidden");
  noteGrid.classList.add("is-hidden");
  traceView.classList.add("is-hidden");
  genericResult.classList.add("is-hidden");
  jsonView.classList.add("is-hidden");
  loadingGrid.classList.toggle("is-hidden", !loading);
}

async function requestApi(url, options = {}) {
  const started = performance.now();
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`HTTP ${response.status} · 响应不是 JSON`);
  }
  state.durationMs = Math.round(performance.now() - started);
  if (!response.ok || payload.code !== 0) {
    throw new Error(payload.message || `HTTP ${response.status}`);
  }
  return payload;
}

function formatCount(count) {
  if (!count) return "0";
  return count.display ?? count.value ?? "0";
}

function recordNote(record) {
  return record?.note || record?.search || record;
}

function extractRecords(data) {
  if (Array.isArray(data?.items)) {
    return data.items
      .filter((item) => item?.search || item?.note || item?.note_id)
      .map((item) => item?.search || item?.note ? item : { search: item });
  }
  if (data?.note_id) return [{ note: data }];
  return [];
}

function pgyBusinessData(data) {
  return data && typeof data === "object" && "success" in data && "data" in data ? data.data : null;
}

function pgyMetric(value) {
  if (value === undefined || value === null || value === "") return { value: null, display: "—" };
  const number = Number(value ?? 0);
  return { value: Number.isFinite(number) ? number : 0, display: String(value ?? 0) };
}

function pgyImageUrl(item) {
  if (typeof item === "string") return item;
  return item?.imageUrl || item?.url || item?.original || item?.masterUrl || item?.previewUrl || "";
}

function normalizePgyNote(data) {
  if (!data || typeof data !== "object") return null;
  if (data.note_id) {
    const liked = data.counts?.liked?.value ?? 0;
    const collected = data.counts?.collected?.value ?? 0;
    const comments = data.counts?.comment?.value ?? 0;
    return {
      ...data,
      pgy_metrics: {
        impNum: data.impNum,
        readNum: data.readNum,
        likeNum: liked,
        favNum: collected,
        cmtNum: comments,
      },
    };
  }
  const noteId = String(data.noteId || data.id || "");
  if (!noteId) return null;
  const rawImages = Array.isArray(data.imagesList) ? data.imagesList : [];
  const imageItems = rawImages.map((item, index) => ({
    index,
    url: pgyImageUrl(item),
    preview_url: pgyImageUrl(item),
    width: typeof item === "object" ? item.width : null,
    height: typeof item === "object" ? item.height : null,
  })).filter((item) => item.url);
  const videoInfo = data.videoInfo && typeof data.videoInfo === "object" ? data.videoInfo : {};
  const videoUrl = videoInfo.masterUrl || videoInfo.playUrl || videoInfo.url || "";
  return {
    note_id: noteId,
    note_url: data.noteLink || `https://www.xiaohongshu.com/explore/${noteId}`,
    type: data.type || (videoUrl ? "video" : "normal"),
    title: data.title || "未命名笔记",
    desc: data.content || data.desc || "",
    time: data.createTime,
    author: {
      user_id: String(data.userId || ""),
      nickname: data.name || "未知作者",
      avatar: data.headPhoto || "",
    },
    counts: {
      liked: pgyMetric(data.likeNum),
      collected: pgyMetric(data.favNum),
      comment: pgyMetric(data.cmtNum),
      share: pgyMetric(data.shareNum),
    },
    images: imageItems.map((item) => item.url),
    image_count: imageItems.length,
    image_items: imageItems,
    video: videoUrl ? { best_url: videoUrl, playable_url: videoUrl, streams: [], stream_count: 1 } : null,
    pgy_metrics: {
      impNum: data.impNum,
      readNum: data.readNum,
      likeNum: data.likeNum,
      favNum: data.favNum,
      cmtNum: data.cmtNum,
    },
    pgy_raw: data,
  };
}

function extractPgyNotes(data) {
  const note = normalizePgyNote(pgyBusinessData(data));
  return note ? [note] : [];
}

function formatPgyTime(value) {
  if (!value) return "时间未提供";
  const numeric = Number(value);
  const date = new Date(Number.isFinite(numeric) ? (numeric < 1000000000000 ? numeric * 1000 : numeric) : value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function renderPgyNoteCard(note) {
  const card = createElement("button", "pgy-note-card-rich");
  card.type = "button";
  card.setAttribute("aria-label", `查看笔记：${note.title}`);
  const cover = createElement("div", "pgy-note-rich-cover");
  const coverUrl = note.images?.[0] || "";
  if (coverUrl) {
    const image = createElement("img");
    image.src = coverUrl;
    image.alt = `${note.title}封面`;
    image.referrerPolicy = "no-referrer";
    cover.append(image);
  } else {
    cover.append(createElement("div", "cover-fallback", "R"));
  }
  cover.append(createElement("span", "note-kind", note.video?.best_url ? "视频笔记" : `${note.image_count || 0} 图`));

  const body = createElement("div", "pgy-note-rich-body");
  const meta = createElement("div", "pgy-note-rich-meta");
  const author = createElement("div", "pgy-note-rich-author");
  if (note.author?.avatar) {
    const avatar = createElement("img");
    avatar.src = note.author.avatar;
    avatar.alt = `${note.author.nickname || "作者"}头像`;
    avatar.referrerPolicy = "no-referrer";
    author.append(avatar);
  }
  author.append(createElement("span", "", note.author?.nickname || "未知作者"));
  meta.append(author, createElement("time", "", formatPgyTime(note.time)));
  body.append(meta, createElement("h3", "", note.title));
  if (note.desc) body.append(createElement("p", "pgy-note-rich-desc", note.desc));

  const metrics = note.pgy_metrics || {};
  const metricGrid = createElement("div", "pgy-note-rich-metrics");
  [
    ["曝光", metrics.impNum], ["阅读", metrics.readNum], ["点赞", metrics.likeNum],
    ["收藏", metrics.favNum], ["评论", metrics.cmtNum],
  ].forEach(([label, value]) => {
    const item = createElement("div");
    item.append(createElement("b", "", value === undefined || value === null ? "—" : compactNumber(value)), createElement("small", "", label));
    metricGrid.append(item);
  });
  body.append(metricGrid);

  const interactionValues = [Number(metrics.likeNum || 0), Number(metrics.favNum || 0), Number(metrics.cmtNum || 0)];
  const interactionTotal = interactionValues.reduce((sum, value) => sum + value, 0);
  const visual = createElement("div", "pgy-note-interaction-visual");
  const bar = createElement("div", "pgy-note-interaction-bar");
  ["likes", "favorites", "comments"].forEach((kind, index) => {
    const segment = createElement("span", `is-${kind}`);
    segment.style.width = interactionTotal ? `${(interactionValues[index] / interactionTotal) * 100}%` : "0";
    bar.append(segment);
  });
  const legend = createElement("div", "pgy-note-interaction-legend");
  [["点赞", "likes"], ["收藏", "favorites"], ["评论", "comments"]].forEach(([label, kind]) => {
    const item = createElement("span", `is-${kind}`, label);
    legend.append(item);
  });
  visual.append(bar, legend);
  body.append(visual);

  const footer = createElement("div", "pgy-note-rich-footer");
  footer.append(
    createElement("span", "", note.data_source === "xhs_web_fallback" ? "小红书详情回退" : "蒲公英详情"),
    createElement("strong", "", "查看完整内容"),
  );
  body.append(footer);
  card.append(cover, body);
  card.addEventListener("click", () => openDrawer({ note }, card));
  return card;
}

function renderPgyNotes(notes) {
  noteGrid.className = "note-grid pgy-note-result-grid";
  noteGrid.replaceChildren(...notes.map(renderPgyNoteCard));
  noteGrid.classList.toggle("is-hidden", state.view !== "cards");
}

function extractPgyBloggers(data) {
  const business = pgyBusinessData(data);
  if (Array.isArray(business?.kols)) return business.kols;
  if (business?.profile && typeof business.profile === "object") {
    return [{ ...business.profile, __pgy_detail: business }];
  }
  return [];
}

function compactNumber(value) {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return Number.isFinite(number) ? number.toLocaleString("zh-CN") : "0";
}

function pgyBloggerTags(blogger) {
  const tags = [];
  (blogger.contentTags || []).forEach((item) => {
    if (typeof item === "string") tags.push(item);
    else if (item?.taxonomy1Tag) tags.push(item.taxonomy1Tag, ...(item.taxonomy2Tags || []));
  });
  tags.push(...(blogger.personalTags || []), ...(blogger.featureTags || []));
  return [...new Set(tags.filter(Boolean))];
}

function renderPgyBloggerCard(blogger) {
  const card = createElement("button", "pgy-blogger-card");
  card.type = "button";
  card.setAttribute("aria-label", `查看博主：${blogger.name || blogger.userId || "未知博主"}`);

  const header = createElement("div", "pgy-blogger-header");
  const avatar = createElement("img", "pgy-blogger-avatar");
  avatar.src = blogger.headPhoto || "";
  avatar.alt = `${blogger.name || "博主"}头像`;
  avatar.loading = "lazy";
  avatar.referrerPolicy = "no-referrer";
  avatar.addEventListener("error", () => avatar.classList.add("is-error"));
  const identity = createElement("div", "pgy-blogger-identity");
  identity.append(
    createElement("h3", "", blogger.name || "未命名博主"),
    createElement("p", "", `小红书号 ${blogger.redId || "—"}`),
    createElement("small", "", blogger.location || "地域未公开"),
  );
  header.append(avatar, identity);

  const tags = createElement("div", "pgy-blogger-tags");
  pgyBloggerTags(blogger).slice(0, 5).forEach((tag) => tags.append(createElement("span", "tag", tag)));

  const metrics = createElement("div", "pgy-blogger-metrics");
  [
    ["粉丝", compactNumber(blogger.fansNum ?? blogger.fansCount)],
    ["阅读中位", compactNumber(blogger.clickMidNum)],
    ["互动中位", compactNumber(blogger.interMidNum ?? blogger.mEngagementNum)],
    ["最低报价", blogger.lowerPrice ? `¥${compactNumber(blogger.lowerPrice)}` : "—"],
  ].forEach(([label, value]) => {
    const metric = createElement("div");
    metric.append(createElement("b", "", value), createElement("small", "", label));
    metrics.append(metric);
  });

  const notePreview = createElement("div", "pgy-blogger-notes");
  (blogger.noteList || []).slice(0, 2).forEach((note) => {
    const item = createElement("div", "pgy-blogger-note");
    const image = createElement("img");
    image.src = note.imageUrl || "";
    image.alt = "近期笔记封面";
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    item.append(image, createElement("span", "", note.contentTag || (Number(note.noteType) === 2 ? "视频" : "图文")));
    notePreview.append(item);
  });
  if (!notePreview.children.length) notePreview.append(createElement("div", "pgy-blogger-note-empty", "暂无近期笔记预览"));

  const footer = createElement("div", "pgy-blogger-footer");
  footer.append(
    createElement("span", "", blogger.gender || blogger.tradeType || "博主"),
    createElement("strong", "", "查看完整资料"),
  );
  card.append(header, tags, metrics, notePreview, footer);
  card.addEventListener("click", () => openPgyBloggerDrawer(blogger, card));
  return card;
}

function renderPgyBloggers(bloggers) {
  noteGrid.className = "note-grid pgy-blogger-grid";
  noteGrid.replaceChildren(...bloggers.map(renderPgyBloggerCard));
  noteGrid.classList.toggle("is-hidden", state.view !== "cards");
}

function addTagRow(parent, tags) {
  if (!Array.isArray(tags) || !tags.length) return;
  const row = createElement("div", "tag-row");
  tags.slice(0, 4).forEach((tag) => row.append(createElement("span", "tag", `# ${tag.name || tag}`)));
  parent.append(row);
}

function renderNoteCard(record) {
  const note = recordNote(record);
  const card = createElement("button", "note-card");
  card.type = "button";
  card.setAttribute("aria-label", `查看笔记：${note.title || "未命名笔记"}`);

  const cover = createElement("div", "note-cover");
  const imageUrl = Array.isArray(note.images) ? note.images[0] : "";
  if (imageUrl) {
    const image = createElement("img");
    image.src = imageUrl;
    image.alt = note.title ? `${note.title} 封面` : "笔记封面";
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => {
      cover.replaceChildren(createElement("div", "cover-fallback", "R"));
    });
    cover.append(image);
  } else {
    cover.append(createElement("div", "cover-fallback", "R"));
  }
  const mediaBadge = note.video?.stream_count
    ? `视频 · ${note.video.stream_count} 流`
    : note.image_count > 1
      ? `${note.image_count} 图`
      : note.type;
  if (mediaBadge) cover.append(createElement("span", "note-kind", mediaBadge));

  const main = createElement("div", "note-main");
  main.append(createElement("h3", "", note.title || "未命名笔记"));
  main.append(createElement("p", "note-author", note.author?.nickname || record.author?.nickname || "未知作者"));
  addTagRow(main, note.tags);
  const stats = createElement("div", "note-stats");
  [["赞", note.counts?.liked], ["藏", note.counts?.collected], ["评", note.counts?.comment]].forEach(([label, value]) => {
    const item = createElement("span");
    item.append(document.createTextNode(`${label} `), createElement("b", "", formatCount(value)));
    stats.append(item);
  });
  main.append(stats);
  card.append(cover, main);
  card.addEventListener("click", () => loadAndOpenNote(record, card));
  return card;
}

async function loadAndOpenNote(record, card) {
  const current = recordNote(record);
  if (record.note || !current.xsec_token || !current.note_id) {
    openDrawer(record, card);
    return;
  }
  card.classList.add("is-loading");
  card.setAttribute("aria-busy", "true");
  try {
    const query = new URLSearchParams({
      xsec_token: current.xsec_token,
      xsec_source: current.xsec_source || "pc_search",
    });
    const payload = await requestApi(`/v1/xhs/notes/${encodeURIComponent(current.note_id)}?${query}`);
    record.note = payload.data;
    openDrawer(record, card);
  } catch (error) {
    showToast(`详情加载失败：${error.message}`);
  } finally {
    card.classList.remove("is-loading");
    card.removeAttribute("aria-busy");
  }
}

function renderNotes(records) {
  noteGrid.className = "note-grid";
  noteGrid.replaceChildren(...records.map(renderNoteCard));
  noteGrid.classList.toggle("is-hidden", state.view !== "cards");
}

function appendKeyValues(parent, object) {
  const grid = createElement("div", "key-value-grid");
  Object.entries(object || {}).forEach(([key, value]) => {
    const item = createElement("div", "key-value");
    const rendered = Array.isArray(value)
      ? `${value.slice(0, 8).map((item) => {
          if (!item || typeof item !== "object") return item;
          const label = item.label ?? item.name ?? item.key ?? item.dateKey ?? "";
          const amount = item.value ?? item.num ?? item.rate ?? item.ratio ?? "";
          return [label, amount].filter((part) => part !== "").join(" ") || JSON.stringify(item);
        }).join(" · ")}${value.length > 8 ? ` · +${value.length - 8}` : ""}`
      : value && typeof value === "object"
        ? JSON.stringify(value)
        : value;
    item.append(createElement("small", "", key), createElement("strong", "", rendered ?? "—"));
    grid.append(item);
  });
  parent.append(grid);
}

function appendComments(parent, comments) {
  const section = createElement("section", "data-section");
  section.append(createElement("h3", "", `评论 · ${comments.length}`));
  comments.forEach((comment) => {
    const item = createElement("article", "comment-item");
    item.append(
      createElement("strong", "", comment.author?.nickname || "用户"),
      createElement("p", "", comment.content || ""),
      createElement("small", "", `赞 ${comment.like_count ?? 0}`),
    );
    section.append(item);
  });
  parent.append(section);
}

function renderGeneric(data) {
  genericResult.replaceChildren();
  if (Array.isArray(data?.comments)) {
    appendComments(genericResult, data.comments);
    appendKeyValues(genericResult, { cursor: data.cursor, has_more: data.has_more });
  } else {
    const section = createElement("section", "data-section");
    section.append(createElement("h3", "", "响应字段"));
    appendKeyValues(section, data);
    genericResult.append(section);
  }
  genericResult.classList.toggle("is-hidden", state.view !== "cards");
}

function renderResponse(payload, title, { keepProgress = false } = {}) {
  state.response = payload;
  state.data = payload.data;
  resultTitle.textContent = title;
  const records = extractRecords(payload.data);
  const pgyNotes = extractPgyNotes(payload.data);
  const bloggers = extractPgyBloggers(payload.data);
  state.resultType = pgyNotes.length ? "pgy_notes" : bloggers.length ? "pgy_bloggers" : records.length ? "notes" : "generic";
  const count = pgyNotes.length || bloggers.length || records.length || payload.data?.items?.length || payload.data?.comments?.length || 1;
  const failedPages = pgyBusinessData(payload.data)?.failed_pages?.length || 0;
  responseMeta.textContent = `${count} 项${failedPages ? ` · ${failedPages} 页失败` : ""} · ${state.durationMs} ms`;
  copyButton.disabled = false;
  csvButton.disabled = false;
  if (!keepProgress) jobProgress.classList.add("is-hidden");
  jsonView.textContent = JSON.stringify(payload, null, 2);
  loadingGrid.classList.add("is-hidden");
  emptyState.classList.add("is-hidden");
  if (pgyNotes.length) renderPgyNotes(pgyNotes);
  else if (bloggers.length) renderPgyBloggers(bloggers);
  else if (records.length) renderNotes(records);
  else renderGeneric(payload.data);
  applyView();
}

function applyView() {
  $$(".view-switch button").forEach((button) => {
    const active = button.dataset.view === state.view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  const records = extractRecords(state.data);
  const pgyNotes = extractPgyNotes(state.data);
  const bloggers = extractPgyBloggers(state.data);
  jsonView.classList.toggle("is-hidden", state.view !== "json" || !state.response);
  noteGrid.classList.toggle("is-hidden", state.view !== "cards" || (!records.length && !pgyNotes.length && !bloggers.length));
  traceView.classList.toggle("is-hidden", state.view !== "trace");
  genericResult.classList.toggle("is-hidden", state.view !== "cards" || records.length || pgyNotes.length || bloggers.length || !state.response);
}

const statusLabels = {
  running: "运行中",
  success: "成功",
  cache_hit: "缓存命中",
  singleflight: "请求合并",
  error: "失败",
};

const stageLabels = {
  queued: "等待调度",
  search: "搜索笔记",
  user_search: "搜索用户",
  user_collections: "收藏笔记",
  detail: "笔记详情",
  author: "作者资料",
  author_notes: "作者笔记",
  comments: "评论",
  sub_comments: "二级评论",
  gpt: "GPT 补全",
  save: "保存结果",
  completed: "采集完成",
};

function renderTrace(job = state.job) {
  state.trace = Array.isArray(job?.events) ? job.events : state.trace;
  $("#trace-count").textContent = String(state.trace.length);
  traceView.replaceChildren();

  const completed = state.trace.filter((event) => ["success", "cache_hit", "singleflight"].includes(event.status)).length;
  const cached = state.trace.filter((event) => ["cache_hit", "singleflight"].includes(event.status)).length;
  const failed = state.trace.filter((event) => event.status === "error").length;
  const runtime = job?.runtime || {};
  const summary = createElement("div", "trace-summary");
  [["完成调用", completed], ["缓存 / 合并", cached], ["失败", failed], ["峰值 Worker", runtime.pool?.peak_active ?? 0]].forEach(([label, value]) => {
    const item = createElement("div");
    item.append(createElement("small", "", label), createElement("strong", "", value));
    summary.append(item);
  });

  const list = createElement("div", "trace-list");
  if (!state.trace.length) {
    list.append(createElement("div", "trace-empty", "等待第一个接口返回"));
  } else {
    state.trace.forEach((event) => {
      const details = createElement("details", "trace-event");
      details.dataset.status = event.status || "running";
      const row = createElement("summary");
      row.append(createElement("span", "trace-status", statusLabels[event.status] || event.status));
      const main = createElement("span", "trace-main");
      main.append(
        createElement("b", "", event.interface || event.stage),
        createElement("small", "", event.target || stageLabels[event.stage] || ""),
      );
      row.append(main);
      row.append(createElement("span", "trace-timing", event.duration_ms === undefined ? "—" : `${event.duration_ms} ms`));

      const body = createElement("div", "trace-detail");
      const facts = createElement("dl");
      [["阶段", stageLabels[event.stage] || event.stage], ["Worker", event.worker_id || "—"], ["排队", event.queue_wait_ms === undefined ? "—" : `${event.queue_wait_ms} ms`]].forEach(([label, value]) => {
        const item = createElement("div");
        item.append(createElement("dt", "", label), createElement("dd", "", value));
        facts.append(item);
      });
      body.append(facts);
      const payload = event.error ? { error: event.error } : (event.response || { status: event.status });
      body.append(createElement("pre", "trace-response", JSON.stringify(payload, null, 2)));
      details.append(row, body);
      list.append(details);
    });
  }
  traceView.append(summary, list);
}

function updateJobProgress(job) {
  const progress = job.progress || { completed: 0, total: 0, percent: 0 };
  const pool = job.runtime?.pool || {};
  jobProgress.classList.remove("is-hidden");
  $("#progress-state").textContent = stageLabels[job.stage] || job.stage || "采集中";
  $("#progress-count").textContent = `${progress.completed} / ${progress.total}`;
  $("#pool-state").textContent = `Worker ${pool.active || 0}/${pool.effective_workers || 0} · 排队 ${pool.queued || 0}`;
  $("#progress-bar").style.width = `${progress.percent || 0}%`;
  const track = $(".progress-track");
  track.setAttribute("aria-valuenow", String(progress.percent || 0));
  renderTrace(job);
}

function sleep(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function pollCollectorJob(jobId) {
  while (state.activeJobId === jobId) {
    const payload = await requestApi(`/v1/xhs/collect/jobs/${encodeURIComponent(jobId)}`);
    const job = payload.data;
    state.job = job;
    updateJobProgress(job);
    resultTitle.textContent = job.status === "completed" ? `“${job.result?.keyword || ""}” 的采集结果` : "采集进行中";
    responseMeta.textContent = `${job.progress.completed}/${job.progress.total} 调用`;

    if (job.status === "completed") {
      state.activeJobId = null;
      localStorage.removeItem("xhs_active_job");
      const finalPayload = {
        code: 0,
        message: "success",
        request_id: job.job_id,
        data: job.result,
      };
      renderResponse(finalPayload, `“${job.result.keyword}” 的采集结果`, { keepProgress: true });
      state.view = "trace";
      applyView();
      return job;
    }
    if (["failed", "cancelled"].includes(job.status)) {
      state.activeJobId = null;
      localStorage.removeItem("xhs_active_job");
      throw new Error(job.error || "采集任务失败");
    }
    await sleep(450);
  }
  return null;
}

function countEstimate() {
  const form = new FormData(collectorForm);
  const pages = Number(form.get("pages") || 1);
  const notes = Number(form.get("note_limit") || 1);
  const detail = form.get("include_details") ? notes : 0;
  const authors = form.get("include_authors") ? notes : 0;
  const comments = form.get("include_comments") ? notes * Number(form.get("comment_pages") || 1) : 0;
  $("#request-estimate").textContent = `约 ${pages + detail + authors + comments} 次请求`;
  $("#comment-pages-field").hidden = !form.get("include_comments");
}

function formBoolean(formData, name) {
  return formData.get(name) === "on";
}

collectorForm.addEventListener("input", countEstimate);
collectorForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#collector-error");
  error.textContent = "";
  const button = $("#collect-button");
  button.dataset.defaultLabel = "开始采集";
  const form = new FormData(collectorForm);
  const body = {
    keyword: String(form.get("keyword") || "").trim(),
    pages: Number(form.get("pages")),
    page_size: 20,
    note_limit: Number(form.get("note_limit")),
    include_details: formBoolean(form, "include_details"),
    include_authors: formBoolean(form, "include_authors"),
    include_comments: formBoolean(form, "include_comments"),
    comment_pages: Number(form.get("comment_pages")),
    use_gpt: formBoolean(form, "use_gpt"),
    save: formBoolean(form, "save"),
    sort: String(form.get("sort")),
    note_type: Number(form.get("note_type")),
  };
  setLoading(true, button);
  try {
    const payload = await requestApi("/v1/xhs/collect/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.job = payload.data;
    state.trace = [];
    state.response = null;
    state.data = null;
    state.activeJobId = payload.data.job_id;
    state.view = "trace";
    localStorage.setItem("xhs_active_job", state.activeJobId);
    loadingGrid.classList.add("is-hidden");
    resultTitle.textContent = "采集进行中";
    updateJobProgress(payload.data);
    applyView();
    const completed = await pollCollectorJob(state.activeJobId);
    if (completed?.result?.output_path) showToast("JSONL 已保存");
  } catch (requestError) {
    loadingGrid.classList.add("is-hidden");
    if (state.job) {
      state.view = "trace";
      renderTrace(state.job);
      applyView();
    }
    error.textContent = requestError.message;
    resultTitle.textContent = "请求失败";
  } finally {
    button.disabled = false;
    $("span", button).textContent = "开始采集";
  }
});

function renderEndpointFields() {
  const definition = endpointDefinitions[$("#endpoint-select").value];
  $("#method-badge").textContent = definition.method;
  const container = $("#endpoint-fields");
  container.replaceChildren();
  definition.fields.forEach((field) => {
    const label = createElement("label", "field");
    label.append(createElement("span", "", field.label));
    let input;
    if (field.type === "select") {
      input = createElement("select");
      field.options.forEach(([value, text]) => {
        const option = createElement("option", "", text);
        option.value = value;
        option.selected = value === field.value;
        input.append(option);
      });
    } else if (field.type === "checkbox") {
      input = createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(field.value);
    } else {
      input = createElement("input");
      input.type = field.type || "text";
      input.value = field.value;
      if (field.placeholder) input.placeholder = field.placeholder;
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
    }
    input.name = field.name;
    input.required = Boolean(field.required);
    label.append(input);
    container.append(label);
  });
}

function renderPgyEndpointFields() {
  const definition = pgyEndpointDefinitions[$("#pgy-endpoint-select").value];
  $("#pgy-method-badge").textContent = definition.method;
  const container = $("#pgy-endpoint-fields");
  container.replaceChildren();
  if (definition.customForm === "square") {
    renderPgySquareFilters(container);
    updatePgySquareLayout();
    void hydratePgySquareFilters();
    return;
  }
  updatePgySquareLayout();
  if (definition.jsonBody) {
    const label = createElement("label", "field");
    label.append(createElement("span", "", "请求体 JSON"));
    const textarea = createElement("textarea");
    textarea.name = "body";
    textarea.spellcheck = false;
    textarea.value = JSON.stringify(definition.value, null, 2);
    label.append(textarea);
    container.append(label);
    return;
  }
  definition.fields.forEach((field) => {
    const label = createElement("label", "field");
    label.append(createElement("span", "", field.label));
    let input;
    if (field.type === "select") {
      input = createElement("select");
      field.options.forEach(([value, text]) => {
        const option = createElement("option", "", text);
        option.value = value;
        option.selected = value === String(field.value);
        input.append(option);
      });
    } else {
      input = createElement("input");
      input.type = field.type || "text";
      input.value = field.value;
      if (field.placeholder) input.placeholder = field.placeholder;
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
    }
    input.name = field.name;
    input.required = Boolean(field.required);
    label.append(input);
    container.append(label);
  });
}

$("#endpoint-select").addEventListener("change", renderEndpointFields);
endpointForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#endpoint-error");
  error.textContent = "";
  const button = $("#endpoint-button");
  button.dataset.defaultLabel = "发送请求";
  const definition = endpointDefinitions[$("#endpoint-select").value];
  state.job = null;
  state.trace = [];
  state.view = definition.view || "cards";
  $("#trace-count").textContent = "0";
  jobProgress.classList.add("is-hidden");
  const form = new FormData(endpointForm);
  let path = definition.path;
  const query = new URLSearchParams();
  definition.fields.forEach((field) => {
    const value = field.type === "checkbox" ? String(form.get(field.name) === "on") : String(form.get(field.name) ?? "");
    if (field.path) path = path.replace(`{${field.name}}`, encodeURIComponent(value));
    else if (value !== "") query.set(field.name, value);
  });
  const url = query.size ? `${path}?${query}` : path;
  setLoading(true, button);
  try {
    const payload = await requestApi(url);
    renderResponse(payload, $("#endpoint-select").selectedOptions[0].textContent);
  } catch (requestError) {
    setLoading(false, button);
    error.textContent = requestError.message;
    resultTitle.textContent = "请求失败";
  } finally {
    button.disabled = false;
    $("span", button).textContent = "发送请求";
  }
});

$("#pgy-endpoint-select").addEventListener("change", renderPgyEndpointFields);

async function requestPgyPages(definition, body) {
  const pagesRequested = Math.max(1, Number(body.pages || 1));
  const started = performance.now();
  const kols = [];
  const seen = new Set();
  const failedPages = [];
  const trackErrors = [];
  let template = null;
  let businessTemplate = {};
  let trackId = "";
  let total = 0;
  let pagesAttempted = 0;
  let pagesFetched = 0;
  let lastPage = 0;

  for (let pageNum = 1; pageNum <= pagesRequested; pageNum += 1) {
    pagesAttempted += 1;
    lastPage = pageNum;
    resultTitle.textContent = `蒲公英抓取中 · ${pageNum}/${pagesRequested} 页`;
    responseMeta.textContent = `已完成 ${pageNum - 1}/${pagesRequested} 页 · ${kols.length} 项`;
    const pageBody = { ...body, pages: 1, page_num: pageNum };
    if (trackId && definition.customForm === "square") pageBody.track_id = trackId;
    try {
      const pagePayload = await requestApi(definition.path, {
        method: definition.method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pageBody),
      });
      template = pagePayload;
      const pageData = pgyBusinessData(pagePayload.data) || {};
      if (!Object.keys(businessTemplate).length) businessTemplate = { ...pageData };
      if (pageData.trackId) trackId = pageData.trackId;
      if (pageData.track_error) trackErrors.push({ page: pageNum, error: pageData.track_error });
      (pageData.failed_pages || []).forEach((failure) => failedPages.push(failure));
      pagesFetched += Number(pageData.pages_fetched ?? 1);
      total = Number(pageData.total || total || 0);
      const rows = Array.isArray(pageData.kols) ? pageData.kols : [];
      rows.forEach((row) => {
        const identity = String(row.userId || row.user_id || "");
        if (identity && seen.has(identity)) return;
        if (identity) seen.add(identity);
        kols.push(row);
      });
      responseMeta.textContent = `已完成 ${pageNum}/${pagesRequested} 页 · ${kols.length} 项`;
      if (!rows.length && !(pageData.failed_pages || []).length) break;
      if (total > 0 && total < 5000 && kols.length >= total) break;
    } catch (error) {
      failedPages.push({ page: pageNum, error: error.message || String(error) });
      responseMeta.textContent = `已完成 ${pageNum}/${pagesRequested} 页 · ${failedPages.length} 页失败`;
    }
  }

  const business = {
    ...businessTemplate,
    kols,
    total,
    pages_requested: pagesRequested,
    pages_attempted: pagesAttempted,
    pages_fetched: pagesFetched,
    failed_pages: failedPages,
    track_errors: trackErrors,
    start_page: 1,
    last_page: lastPage,
    page_size: definition.customForm === "square" ? 20 : 4,
    returned: kols.length,
    trackId: trackId || businessTemplate.trackId,
  };
  const upstream = template?.data || { code: 0, msg: "success", success: true };
  state.durationMs = Math.round(performance.now() - started);
  return {
    ...(template || { code: 0, message: "success", request_id: crypto.randomUUID() }),
    data: { ...upstream, data: business },
  };
}

pgyEndpointForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#pgy-endpoint-error");
  error.textContent = "";
  const button = $("#pgy-endpoint-button");
  button.dataset.defaultLabel = "发送蒲公英请求";
  const definition = pgyEndpointDefinitions[$("#pgy-endpoint-select").value];
  state.job = null;
  state.trace = [];
  state.view = definition.view || "json";
  $("#trace-count").textContent = "0";
  jobProgress.classList.add("is-hidden");
  setLoading(true, button);
  try {
    const form = new FormData(pgyEndpointForm);
    let body;
    if (definition.customForm === "square") {
      body = buildPgySquareBody(pgyEndpointForm);
    } else if (definition.jsonBody) {
      body = JSON.parse(String(form.get("body") || "{}"));
    } else if (definition.method !== "GET") {
      body = {};
      definition.fields.forEach((field) => {
        const value = form.get(field.name);
        if (value !== null && value !== "") body[field.name] = field.numeric || field.type === "number" ? Number(value) : String(value);
      });
    }
    let payload;
    if (["similar", "square"].includes($("#pgy-endpoint-select").value)) {
      payload = await requestPgyPages(definition, body);
    } else {
      const options = definition.method === "GET"
        ? {}
        : {
            method: definition.method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          };
      payload = await requestApi(definition.path, options);
    }
    renderResponse(payload, $("#pgy-endpoint-select").selectedOptions[0].textContent);
  } catch (requestError) {
    setLoading(false, button);
    error.textContent = requestError instanceof SyntaxError ? `请求体 JSON 格式错误：${requestError.message}` : requestError.message;
    resultTitle.textContent = "蒲公英请求失败";
  } finally {
    button.disabled = false;
    $("span", button).textContent = "发送蒲公英请求";
  }
});

$$('.mode-tab').forEach((tab) => {
  tab.addEventListener("click", () => {
    if (state.activeJobId && tab.dataset.mode !== "collector") {
      showToast("采集任务运行中");
      return;
    }
    $$('.mode-tab').forEach((item) => {
      const active = item === tab;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-selected", String(active));
    });
    const mode = tab.dataset.mode;
    collectorForm.classList.toggle("is-hidden", mode !== "collector");
    endpointForm.classList.toggle("is-hidden", mode !== "endpoint");
    pgyEndpointForm.classList.toggle("is-hidden", mode !== "pgy");
    updatePgySquareLayout();
  });
});

$$('.view-switch button[data-view]').forEach((button) => {
  button.addEventListener("click", () => {
    state.view = button.dataset.view;
    if (state.view === "trace") renderTrace(state.job || { events: state.trace });
    applyView();
  });
});

copyButton.addEventListener("click", async () => {
  if (!state.response) return;
  await navigator.clipboard.writeText(JSON.stringify(state.response, null, 2));
  showToast("JSON 已复制");
});

function csvSourceRows() {
  const pgyNotes = extractPgyNotes(state.data);
  if (pgyNotes.length) return pgyNotes.map((note) => note.pgy_raw || note);

  const bloggers = extractPgyBloggers(state.data);
  if (bloggers.length) {
    return bloggers.map((blogger) => {
      const { __pgy_detail: detail, ...profile } = blogger;
      return detail ? { ...profile, detail } : profile;
    });
  }

  const records = extractRecords(state.data);
  if (records.length) return records;

  const business = pgyBusinessData(state.data);
  const source = business ?? state.data;
  if (Array.isArray(source)) return source;
  for (const key of ["items", "list", "comments", "records", "data"]) {
    if (Array.isArray(source?.[key])) return source[key];
  }
  return source === undefined || source === null ? [] : [source];
}

function flattenCsvRow(value, prefix = "", target = {}) {
  if (value === null || value === undefined) {
    if (prefix) target[prefix] = "";
    return target;
  }
  if (Array.isArray(value)) {
    if (prefix) target[prefix] = JSON.stringify(value);
    return target;
  }
  if (typeof value !== "object") {
    target[prefix || "value"] = value;
    return target;
  }
  const entries = Object.entries(value);
  if (!entries.length && prefix) target[prefix] = "{}";
  entries.forEach(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    flattenCsvRow(item, path, target);
  });
  return target;
}

function csvCell(value) {
  let text = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@]/.test(text.trimStart())) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function buildCsv(rows) {
  const flatRows = rows.map((row) => flattenCsvRow(row));
  const columns = [];
  const sourceKeys = new Set();
  const exportKeys = new Set();
  flatRows.forEach((row) => Object.keys(row).forEach((key) => {
    if (sourceKeys.has(key)) return;
    sourceKeys.add(key);
    let label = key;
    let suffix = 2;
    while (exportKeys.has(label.toLowerCase())) {
      label = `${key}_${suffix}`;
      suffix += 1;
    }
    exportKeys.add(label.toLowerCase());
    columns.push({ source: key, label });
  }));
  if (!columns.length) columns.push({ source: "value", label: "value" });
  return [
    columns.map((column) => csvCell(column.label)).join(","),
    ...flatRows.map((row) => columns.map((column) => csvCell(row[column.source])).join(",")),
  ].join("\r\n");
}

function csvFilename() {
  const title = String(resultTitle.textContent || "xhs-collector")
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 60);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `${title || "xhs-collector"}-${stamp}.csv`;
}

csvButton.addEventListener("click", () => {
  if (!state.response) return;
  const rows = csvSourceRows();
  if (!rows.length) {
    showToast("当前结果没有可导出的记录");
    return;
  }
  const blob = new Blob(["\ufeff", buildCsv(rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = csvFilename();
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast(`已导出 ${rows.length} 条 CSV 记录`);
});

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "—";
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function appendVideoMedia(parent, note) {
  const videoData = note.video;
  if (!videoData?.best_url) return false;
  const player = createElement("video", "drawer-video");
  player.controls = true;
  player.preload = "none";
  player.playsInline = true;
  player.referrerPolicy = "no-referrer";
  player.src = videoData.playable_url || videoData.best_url;
  if (note.images?.[0]) player.poster = note.images[0];
  parent.append(player);

  const section = createElement("section", "drawer-section media-section");
  const heading = createElement("div", "media-heading");
  heading.append(
    createElement("h3", "", `视频流 · ${videoData.stream_count || videoData.streams?.length || 0}`),
    createElement("span", "", videoData.duration_ms ? `${Math.round(videoData.duration_ms / 1000)} 秒` : ""),
  );
  section.append(heading);
  const streamList = createElement("div", "stream-list");
  (videoData.streams || []).forEach((stream) => {
    const link = createElement("a", "stream-link");
    link.href = stream.master_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.referrerPolicy = "no-referrer";
    const resolution = stream.width && stream.height ? `${stream.width} × ${stream.height}` : "未知尺寸";
    const labels = [];
    if (stream.master_url === videoData.best_url) labels.push("最高画质");
    if (stream.master_url === videoData.playable_url) labels.push("浏览器兼容");
    link.append(
      createElement("b", "", `${labels.length ? `${labels.join(" / ")} · ` : ""}${resolution}`),
      createElement("small", "", `${stream.quality || stream.format || "MP4"} · ${stream.codec || "video"} · ${formatBytes(stream.size)}`),
    );
    streamList.append(link);
  });
  section.append(streamList);
  parent.append(section);
  return true;
}

function appendImageGallery(parent, note) {
  const images = Array.isArray(note.image_items) && note.image_items.length
    ? note.image_items
    : (note.images || []).map((url, index) => ({ index, url, preview_url: url }));
  if (!images.length) return false;
  const section = createElement("section", "drawer-section media-section");
  const heading = createElement("div", "media-heading");
  heading.append(createElement("h3", "", `全部图片 · ${images.length}`));
  section.append(heading);
  const gallery = createElement("div", "media-gallery");
  images.forEach((image, index) => {
    const item = createElement("figure", "media-item");
    const link = createElement("a");
    link.href = image.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.referrerPolicy = "no-referrer";
    const element = createElement("img");
    element.src = image.preview_url || image.url;
    element.alt = `${note.title || "笔记"} 第 ${index + 1} 张图`;
    element.loading = index < 2 ? "eager" : "lazy";
    element.referrerPolicy = "no-referrer";
    link.append(element);
    const caption = createElement("figcaption");
    caption.append(
      createElement("span", "", `${index + 1} / ${images.length}`),
      createElement("span", "", image.width && image.height ? `${image.width} × ${image.height}` : ""),
    );
    item.append(link, caption);
    if (image.live_photo_url) {
      const liveLink = createElement("a", "live-photo-link", "Live Photo");
      liveLink.href = image.live_photo_url;
      liveLink.target = "_blank";
      liveLink.rel = "noreferrer";
      liveLink.referrerPolicy = "no-referrer";
      item.append(liveLink);
    }
    gallery.append(item);
  });
  section.append(gallery);
  parent.append(section);
  return true;
}

function pickPgyFields(source, keys) {
  return Object.fromEntries(
    keys.filter((key) => source?.[key] !== undefined && source?.[key] !== null).map((key) => [key, source[key]]),
  );
}

function appendPgyDataSection(parent, title, data, keys = []) {
  if (!data || typeof data !== "object") return;
  const section = createElement("section", "drawer-section pgy-drawer-section");
  section.append(createElement("h3", "", title));
  const selected = keys.length ? pickPgyFields(data, keys) : {};
  if (Object.keys(selected).length) appendKeyValues(section, selected);
  const raw = createElement("details", "pgy-raw-details");
  raw.append(
    createElement("summary", "", `查看原始字段 · ${Object.keys(data).length}`),
    createElement("pre", "trace-response", JSON.stringify(data, null, 2)),
  );
  section.append(raw);
  parent.append(section);
}

function appendPgyRecentNotes(parent, blogger) {
  const notes = Array.isArray(blogger.noteList) ? blogger.noteList : [];
  if (!notes.length) return;
  const section = createElement("section", "drawer-section pgy-drawer-section");
  section.append(createElement("h3", "", `近期笔记 · ${notes.length}`));
  const grid = createElement("div", "pgy-drawer-notes");
  notes.forEach((note) => {
    const item = createElement("div", "pgy-drawer-note");
    const image = createElement("img");
    image.src = note.imageUrl || "";
    image.alt = "近期笔记封面";
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    item.append(
      image,
      createElement("b", "", note.contentTag || (Number(note.noteType) === 2 ? "视频笔记" : "图文笔记")),
      createElement("small", "", note.noteId || ""),
    );
    grid.append(item);
  });
  section.append(grid);
  parent.append(section);
}

function showDetailDrawer(trigger) {
  state.lastFocusedCard = trigger;
  const drawer = $("#detail-drawer");
  const backdrop = $("#drawer-backdrop");
  backdrop.hidden = false;
  requestAnimationFrame(() => backdrop.classList.add("is-open"));
  drawer.classList.add("is-open");
  drawer.setAttribute("aria-hidden", "false");
  $("#close-drawer").focus();
}

async function openPgyBloggerDrawer(blogger, trigger) {
  trigger.classList.add("is-loading");
  trigger.setAttribute("aria-busy", "true");
  $("#drawer-title").textContent = blogger.name || "博主详情";
  $("#drawer-eyebrow").textContent = "BLOGGER DETAIL";
  const content = $("#drawer-content");
  content.replaceChildren(createElement("div", "drawer-loading", "正在加载博主完整资料…"));
  showDetailDrawer(trigger);
  try {
    let detail = blogger.__pgy_detail;
    if (!detail) {
      const payload = await requestApi("/v1/xhs/pgy/get_blogger_detail", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: blogger.userId, business: 0, increase_type: 1, date_type: 1 }),
      });
      detail = payload.data?.data || {};
      blogger.__pgy_detail = detail;
    }
    const profile = detail.profile || blogger;
    content.replaceChildren();

    const hero = createElement("section", "pgy-drawer-hero");
    const avatar = createElement("img", "pgy-drawer-avatar");
    avatar.src = profile.headPhoto || blogger.headPhoto || "";
    avatar.alt = `${profile.name || blogger.name || "博主"}头像`;
    avatar.referrerPolicy = "no-referrer";
    const identity = createElement("div");
    identity.append(
      createElement("h3", "", profile.name || blogger.name || "未命名博主"),
      createElement("p", "", `小红书号 ${profile.redId || blogger.redId || "—"}`),
      createElement("small", "", profile.location || blogger.location || "地域未公开"),
    );
    hero.append(avatar, identity);
    content.append(hero);

    const tags = createElement("div", "tag-row pgy-drawer-tags");
    pgyBloggerTags({ ...blogger, ...profile }).slice(0, 12).forEach((tag) => tags.append(createElement("span", "tag", tag)));
    if (tags.children.length) content.append(tags);

    const metrics = createElement("section", "drawer-section");
    metrics.append(createElement("h3", "", "核心数据"));
    const metricGrid = createElement("div", "drawer-metrics");
    [
      ["粉丝", profile.fansNum ?? blogger.fansNum],
      ["图文报价", profile.picturePrice ?? blogger.picturePrice],
      ["视频报价", profile.videoPrice ?? blogger.videoPrice],
      ["阅读中位", blogger.clickMidNum],
    ].forEach(([label, value]) => {
      const metric = createElement("div", "drawer-metric");
      const rendered = label.includes("报价") && value ? `¥${compactNumber(value)}` : compactNumber(value);
      metric.append(createElement("b", "", rendered), createElement("small", "", label));
      metricGrid.append(metric);
    });
    metrics.append(metricGrid);
    content.append(metrics);

    appendPgyRecentNotes(content, blogger);
    appendPgyDataSection(content, "博主资料", profile, [
      "userId", "name", "redId", "location", "gender", "fansNum", "picturePrice", "videoPrice",
      "cooperateState", "mcnName", "institutionName",
    ]);
    appendPgyDataSection(content, "数据概览", detail.data_summary, [
      "estimatePictureCpm", "estimateVideoCpm", "pictureReadCost", "videoReadCost",
      "inviteReply48hNumRatio", "fans30GrowthRate", "activeDays7d",
    ]);
    appendPgyDataSection(content, "粉丝核心指标", detail.fans_summary, [
      "fansNum", "fansIncreaseNum", "fansGrowthRate", "activeFansRate", "readFansRate",
      "engageFansRate", "activeFansBeyondRate", "engageFansBeyondRate",
    ]);
    appendPgyDataSection(content, "粉丝画像", detail.fans_profile, [
      "gender", "ages", "provinces", "cities", "devices", "interests",
    ]);
    appendPgyDataSection(content, "粉丝趋势", detail.fans_history, [
      "fansNumInc", "fansNumIncRate",
    ]);
  } catch (error) {
    content.replaceChildren(createElement("p", "drawer-error", `博主详情加载失败：${error.message}`));
  } finally {
    trigger.classList.remove("is-loading");
    trigger.removeAttribute("aria-busy");
  }
}

function openDrawer(record, trigger) {
  state.lastFocusedCard = trigger;
  const note = recordNote(record);
  $("#drawer-eyebrow").textContent = "NOTE DETAIL";
  $("#drawer-title").textContent = note.title || "笔记详情";
  const content = $("#drawer-content");
  content.replaceChildren();
  const hasVideo = appendVideoMedia(content, note);
  if (!hasVideo) appendImageGallery(content, note);
  if (note.desc) content.append(createElement("p", "drawer-desc", note.desc));
  addTagRow(content, note.tags);

  const metrics = createElement("section", "drawer-section");
  metrics.append(createElement("h3", "", "互动数据"));
  const metricGrid = createElement("div", "drawer-metrics");
  const drawerMetrics = note.pgy_metrics
    ? [
        ["曝光", pgyMetric(note.pgy_metrics.impNum)],
        ["阅读", pgyMetric(note.pgy_metrics.readNum)],
        ["点赞", pgyMetric(note.pgy_metrics.likeNum)],
        ["收藏", pgyMetric(note.pgy_metrics.favNum)],
        ["评论", pgyMetric(note.pgy_metrics.cmtNum)],
      ]
    : [["点赞", note.counts?.liked], ["收藏", note.counts?.collected], ["评论", note.counts?.comment], ["分享", note.counts?.share]];
  drawerMetrics.forEach(([label, value]) => {
    const metric = createElement("div", "drawer-metric");
    metric.append(createElement("b", "", formatCount(value)), createElement("small", "", label));
    metricGrid.append(metric);
  });
  metrics.append(metricGrid);
  content.append(metrics);

  const author = record.author || note.author;
  if (author) {
    const section = createElement("section", "drawer-section");
    section.append(createElement("h3", "", "作者"));
    appendKeyValues(section, {
      nickname: author.nickname,
      user_id: author.user_id,
      red_id: author.red_id,
      desc: author.desc,
    });
    content.append(section);
  }
  if (record.gpt || note.gpt) {
    const section = createElement("section", "drawer-section");
    section.append(createElement("h3", "", "GPT 补全"));
    appendKeyValues(section, record.gpt || note.gpt);
    content.append(section);
  }
  if (note.pgy_raw) appendPgyDataSection(content, "蒲公英原始字段", note.pgy_raw);
  if (note.data_source) {
    const section = createElement("section", "drawer-section");
    section.append(createElement("h3", "", "数据来源"));
    appendKeyValues(section, { data_source: note.data_source, pgy_access: note.pgy_access });
    content.append(section);
  }
  if (Array.isArray(record.comments)) appendComments(content, record.comments);

  showDetailDrawer(trigger);
}

function closeDrawer() {
  const drawer = $("#detail-drawer");
  const backdrop = $("#drawer-backdrop");
  drawer.classList.remove("is-open");
  drawer.setAttribute("aria-hidden", "true");
  backdrop.classList.remove("is-open");
  window.setTimeout(() => { backdrop.hidden = true; }, 190);
  state.lastFocusedCard?.focus();
}

$("#close-drawer").addEventListener("click", closeDrawer);
$("#drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("#detail-drawer").classList.contains("is-open")) closeDrawer();
});

async function initialize() {
  renderEndpointFields();
  renderPgyEndpointFields();
  countEstimate();
  await loadHealth();
  const savedJobId = localStorage.getItem("xhs_active_job");
  if (!savedJobId) return;
  state.activeJobId = savedJobId;
  state.view = "trace";
  resultTitle.textContent = "恢复采集任务";
  try {
    await pollCollectorJob(savedJobId);
  } catch (error) {
    state.activeJobId = null;
    localStorage.removeItem("xhs_active_job");
    $("#collector-error").textContent = error.message;
  }
}

initialize();
