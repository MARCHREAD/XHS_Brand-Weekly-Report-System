"""Fill the retained coursework template; preserve all unrelated OOXML parts."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import os
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree as E
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / 'output' / 'word-template-20261026'
REF = Path('A:/download/智慧城市技术概论 大作业模板.docx')
OUT = ROOT / 'docs' / '李昊阅_202409010201_智慧城市技术概论大作业.docx'
TMP.mkdir(parents=True, exist_ok=True)
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W, 'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
def tag(n): return '{'+W+'}'+n

def f(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc', size)

def center(d, text, cx, cy, size=28, color='#18283F', bold=False):
    d.multiline_text((cx,cy),text,font=f(size,bold),fill=color,anchor='mm',align='center',spacing=12)

def architecture():
    im=Image.new('RGB',(1800,1050),'white');d=ImageDraw.Draw(im)
    tiers=[('应用层','周报总览  ·  热点追踪  ·  市场机会  ·  竞品与情绪分析','#EAF1FB'),
           ('平台层','原始快照 → 标准化与去重 → 指标聚合 → 主题与情感分析','#EDF6F1'),
           ('网络层','HTTPS 请求  ·  API 服务  ·  分页重试  ·  任务队列','#FEF5E8'),
           ('感知与采集层','公开笔记  ·  作者公开资料  ·  主评论与子评论  ·  互动指标','#EEF2F8')]
    for i,(name,body,fill) in enumerate(tiers):
        y=60+i*220
        d.rounded_rectangle((190,y,1610,y+165),radius=15,fill=fill,outline='#6B819C',width=3)
        d.line((455,y+18,455,y+147),fill='#ADBFD0',width=2)
        center(d,name,320,y+80,33,bold=True)
        center(d,body,1030,y+65,30)
        detail=['品牌营销与运营决策  ·  周报归档与导出（设计）',
                'BrandWeeklySnapshot  ·  evidence 证据索引（设计）',
                '复用现有 FastAPI 与采集任务管理',
                '以公开数字内容作为感知对象，不依赖新增物理传感器'][i]
        center(d,detail,1030,y+117,25,color='#52667C')
        if i<3:
            yy=y+170;d.line((900,yy+45,900,yy+5),fill='#3E658E',width=5)
            d.polygon([(900,yy),(887,yy+17),(913,yy+17)],fill='#3E658E')
    for x,label in [(75,'数据标准与质量'),(1725,'访问控制与审计')]:
        d.rounded_rectangle((x-50,55,x+50,885),radius=14,fill='#F7F8FA',outline='#9BAABA',width=2)
        center(d,'\n'.join(label),x,465,31,bold=True)
    center(d,'数据自下而上汇聚，质量记录贯穿采集、计算与展示',900,1000,28,color='#52667C')
    im.save(TMP/'architecture.png')

def functions():
    im=Image.new('RGB',(1800,1000),'white');d=ImageDraw.Draw(im)
    d.rounded_rectangle((480,28,1320,142),radius=14,fill='#EAF1FB',outline='#526D90',width=3)
    center(d,'品牌营销可视化周报系统',900,84,36,bold=True)
    groups=[('数据管理',['品牌词与竞品词','采集任务与状态','去重与质量记录']),
            ('营销分析',['热点与增长趋势','市场机会代理指标','竞品份额与效率']),
            ('用户评价',['正负向情绪识别','评价点与话题归因','风险样本与证据']),
            ('周报应用',['门户一张图','历史快照与导出','建议行动与复盘'])]
    d.line((900,143,900,218),fill='#6F829B',width=4)
    centers=[235,675,1115,1555]
    d.line((centers[0],218,centers[-1],218),fill='#6F829B',width=4)
    for i,(name,leaves) in enumerate(groups):
        cx=centers[i]; d.line((cx,218,cx,270),fill='#6F829B',width=4)
        d.rounded_rectangle((cx-188,270,cx+188,377),radius=12,fill='#EDF2F8',outline='#6F829B',width=3)
        center(d,name,cx,322,33,bold=True)
        d.line((cx,377,cx,414),fill='#6F829B',width=3)
        for j,text in enumerate(leaves):
            y=430+j*142
            d.rounded_rectangle((cx-188,y,cx+188,y+108),radius=10,fill='white',outline='#8FA2BA',width=2)
            center(d,text,cx,y+54,27)
            if j<2:d.line((cx,y+108,cx,y+142),fill='#8FA2BA',width=3)
    d.rectangle((90,899,1710,978),fill='#F6F8FB',outline='#ACB8C8',width=2)
    center(d,'当前状态：采集基座与门户原型已具备；主题、情感、市场机会与归档为后续开发',900,939,26,color='#52667C')
    im.save(TMP/'functions.png')

async def portal():
    helper=TMP/'capture.cjs'
    helper.write_text('''const {chromium}=require('playwright');
const fs=require('fs'); const path=require('path');
(async()=>{ const b=await chromium.launch({headless:true});
 const page=await b.newPage({viewport:{width:1280,height:980},deviceScaleFactor:1.5});
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.hostname!=='127.0.0.1')return route.abort();
  const pathname=u.pathname.endsWith('/')?u.pathname+'index.html':u.pathname;
  const p=path.join(process.argv[2],pathname);
  if(!fs.existsSync(p))return route.fulfill({status:404,body:''});
  const mime=p.endsWith('.css')?'text/css':p.endsWith('.js')?'text/javascript':'text/html';
  return route.fulfill({status:200,body:fs.readFileSync(p),contentType:mime+'; charset=utf-8'});
 });
 await page.goto('http://127.0.0.1/brand-report/',{waitUntil:'networkidle'});
 await page.screenshot({path:process.argv[3]});
 if(await page.locator('.demo-badge').count()!==1)throw Error('Demo badge missing');
 await b.close();
})().catch(e=>{console.error(e);process.exit(1)});
''',encoding='utf-8')
    env=os.environ.copy()
    env['NODE_PATH']=r'C:\Users\20240\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules'
    subprocess.run([r'C:\Users\20240\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe',str(helper),str(ROOT/'platforms/xiaohongshu/web'),str(TMP/'portal.png')],check=True,env=env)

def build():
    data={}
    with ZipFile(REF) as z:
        data={n:z.read(n) for n in z.namelist()}
    tree=E.fromstring(data['word/document.xml']);body=tree.find(tag('body'))
    original_paras=body.findall(tag('p'))
    prototypes={i:deepcopy(p) for i,p in enumerate(original_paras)}
    sect=deepcopy(body.find(tag('sectPr')))
    table_proto=deepcopy(body.find(tag('tbl')))
    for child in list(body):body.remove(child)

    def prop(el,name,**attrs):
        x=el.find(tag(name))
        if x is None:x=E.SubElement(el,tag(name))
        for k,v in attrs.items():x.set(tag(k),str(v))
        return x

    def paragraph(text, role='body', page=False):
        src={'body':4,'h1':2,'h2':3,'title':0,'name':1,'caption':11}[role]
        p=deepcopy(prototypes[src]);ppr=p.find(tag('pPr'))
        if ppr is None:ppr=E.Element(tag('pPr'));p.insert(0,ppr)
        for c in list(p):
            if c is not ppr:p.remove(c)
        rpr=ppr.find(tag('rPr'))
        if rpr is not None:ppr.remove(rpr)
        if role not in ['h1','h2']:
            num=ppr.find(tag('numPr'))
            if num is not None:ppr.remove(num)
        prop(ppr,'snapToGrid',val='0')
        prop(ppr,'pageBreakBefore',val='1' if page else '0')
        prop(ppr,'keepNext',val='1' if role in ['h1','h2'] else '0')
        prop(ppr,'keepLines',val='1')
        if role=='body':
            prop(ppr,'spacing',line='300',lineRule='auto',before='0',after='0')
            prop(ppr,'ind',firstLine='480',firstLineChars='200')
            prop(ppr,'jc',val='both')
        elif role=='caption':
            prop(ppr,'spacing',line='240',lineRule='auto',before='80',after='100')
            prop(ppr,'ind',firstLine='0',firstLineChars='0')
            prop(ppr,'jc',val='center')
        run=E.SubElement(p,tag('r'));rp=E.SubElement(run,tag('rPr'))
        prop(rp,'rFonts',ascii='宋体',hAnsi='宋体',eastAsia='宋体',cs='Times New Roman')
        prop(rp,'color',val='000000')
        size={'title':44,'name':28,'h1':36,'h2':32,'caption':21,'body':24}[role]
        prop(rp,'sz',val=size);prop(rp,'szCs',val=size)
        prop(rp,'b',val='1' if role in ['title','name','h1','h2'] else '0')
        for i,line in enumerate(text.split('\n')):
            if i:E.SubElement(run,tag('br'))
            t=E.SubElement(run,tag('t'));t.text=line
        body.append(p)
        return p

    def figure(slot,path,caption):
        p=deepcopy(prototypes[slot]);pp=p.find(tag('pPr'))
        prop(pp,'ind',firstLine='0',firstLineChars='0')
        prop(pp,'spacing',line='240',lineRule='auto',before='40',after='0')
        prop(pp,'keepNext',val='1');prop(pp,'snapToGrid',val='0')
        im=Image.open(path);width=4740000; height=int(width*im.height/im.width)
        for ex in p.xpath('.//wp:extent|.//a:xfrm/a:ext',namespaces=NS):
            ex.set('cx',str(width));ex.set('cy',str(height))
        # Each template image has a stable relationship. Replace its payload only.
        for dp in p.xpath('.//wp:docPr',namespaces=NS): dp.set('descr',caption)
        body.append(p);paragraph(caption,'caption')

    def table(headers,rows,widths,caption):
        paragraph(caption,'caption')
        tbl=deepcopy(table_proto)
        for row in tbl.findall(tag('tr')):tbl.remove(row)
        grid=tbl.find(tag('tblGrid'))
        for x in list(grid):grid.remove(x)
        for w in widths:E.SubElement(grid,tag('gridCol')).set(tag('w'),str(w))
        for ri,values in enumerate([headers]+rows):
            tr=E.SubElement(tbl,tag('tr'));trpr=E.SubElement(tr,tag('trPr'))
            E.SubElement(trpr,tag('cantSplit'))
            if ri==0:E.SubElement(trpr,tag('tblHeader'))
            for ci,value in enumerate(values):
                tc=E.SubElement(tr,tag('tc'));tcp=E.SubElement(tc,tag('tcPr'))
                prop(tcp,'tcW',w=widths[ci],type='dxa');prop(tcp,'vAlign',val='center')
                borders=E.SubElement(tcp,tag('tcBorders'))
                if ri in [0,len(rows)]:prop(borders,'bottom',val='single',sz='6',color='000000')
                mar=E.SubElement(tcp,tag('tcMar'));prop(mar,'top',w='65',type='dxa');prop(mar,'bottom',w='65',type='dxa')
                p=E.SubElement(tc,tag('p'));pp=E.SubElement(p,tag('pPr'))
                prop(pp,'spacing',line='240',lineRule='auto',before='0',after='0')
                prop(pp,'snapToGrid',val='0');prop(pp,'jc',val='center' if ci==0 or ri==0 else 'left')
                r=E.SubElement(p,tag('r'));rp=E.SubElement(r,tag('rPr'))
                prop(rp,'rFonts',ascii='宋体',hAnsi='宋体',eastAsia='宋体');prop(rp,'sz',val='21');prop(rp,'color',val='000000')
                if ri==0:prop(rp,'b',val='1')
                E.SubElement(r,tag('t')).text=value
        body.append(tbl)

    # Page 1: topic, student identity and background, reusing the retained title/heading patterns.
    paragraph('基于逆向小红书数据的品牌营销\n可视化周报系统设计与实现','title')
    paragraph('姓名：李昊阅      学号：202409010201','name')
    paragraph('背景','h1')
    paragraph('问题描述','h2')
    paragraph('小红书的消费体验笔记和评论能够反映用户对品牌、产品和服务的关注点。品牌运营人员需要定期汇总声量、热点和用户评价，但人工检索、复制与整理过程分散，统计范围也容易随人员和时间变化。热门话题在一周内可能明显变化，单纯查看累计点赞量或依赖月报，容易错过选题时机；同一产品的正负向评价又常混在长文本中，难以直接归纳原因。')
    paragraph('本项目已有小红书公开数据采集工作台，可获取笔记搜索、详情、作者和评论。现阶段的主要问题不是新增采集入口，而是把采集结果组织成稳定的营销分析流程。因此，本作业将品牌周报作为具体应用，以固定周次、品牌词和竞品词建立统一口径，辅助运营人员识别热点、比较竞品并定位风险反馈。')
    paragraph('系统概述','h2')
    paragraph('本系统面向品牌市场、内容运营与公关人员，在现有小红书数据采集基座上构建品牌营销可视化周报。系统按品牌词和竞品词组织公开笔记、作者资料、评论及互动指标，经过时间窗筛选、去重和字段标准化，形成品牌周报快照；再从热点趋势、市场机会、竞品对标和用户情绪四个角度提炼信息。门户集中显示声量、互动量、正向情绪率、风险话题及对应证据，帮助运营人员形成下周行动。当前已完成采集基座、门户原型和数据契约设计，分析算法、历史归档和自动周报属于后续接入任务。系统使用公开数字内容作为信息感知对象，服务具体的商业运营管理场景。')

    # Page 2: match the reference's sensing/network/platform/application architecture vocabulary.
    paragraph('系统框架','h1',True)
    paragraph('整体框架图','h2')
    figure(10,TMP/'architecture.png','图1 系统整体框架图')
    paragraph('系统参照模板图示的感知层、网络层、平台层和应用层划分职责。对于本项目，感知对象是公开数字内容；四层结构用于说明信息流转关系，并不意味着需要增加物理传感器或建设独立通信网络。')
    paragraph('感知与采集层：复用现有关键词搜索、笔记详情、作者资料和评论接口，以笔记与评论主键关联记录；保存采集时间、响应状态和原始快照，形成后续分析的输入。')
    paragraph('网络层：利用 HTTPS 与平台公开内容服务交互，由本地 FastAPI 提供统一入口。任务管理组件负责分页、排队、重试与运行状态，前端通过本地 HTTP 访问数据与页面。')
    paragraph('平台层：完成去重、文本清洗、品牌匹配和周次聚合，并规划接入热点和情感算法。分析结果封装为 BrandWeeklySnapshot，证据索引用于关联原始笔记和评论。')
    paragraph('应用层：通过品牌周报门户呈现总览、热点、竞品、情绪和建议行动，并规划历史归档及导出。数据标准、字段质量和访问控制贯穿各层，保证口径和来源可追溯。')

    # Page 3.
    paragraph('系统功能','h2',True)
    figure(15,TMP/'functions.png','图2 系统功能结构图')
    paragraph('数据管理负责品牌主词、别名、产品词、竞品词和排除词维护，并组织采集任务、任务状态与数据质量记录。配置需要版本标识，使历史周报能够保留生成时的分析口径。')
    paragraph('营销分析包含热点追踪、市场机会和竞品对标。热点模块按话题声量、环比和互动效率发现关注点；市场机会以样本内讨论增长、主题需求与竞品覆盖差异作为代理指标；竞品模块比较相同时间窗下的声量份额与篇均互动。平台讨论样本不代表行业交易全量，市场规模应结合外部销售数据另行验证。')
    paragraph('用户评价模块规划正文和评论的正向、中性、负向识别，进一步归纳口感、包装、价格、服务等评价点。风险提示保留对应证据，便于人工确认误判、反讽和语境影响。')
    paragraph('周报应用以管理一张图作为入口，通过图表、摘要和证据下钻支持决策；归档保存历史快照，行动项关联负责人和截止时间。当前页面已展示这些模块的布局，行动编辑、历史快照和分析结果尚待后端实现。')

    # Page 4.
    paragraph('管理一张图','h2',True)
    figure(19,TMP/'portal.png','图3 品牌周报门户原型（页面指标均为演示数据）')
    paragraph('门户采用左侧导航和右侧工作区。顶部设置报告周期、刷新与导出入口；主体依次排列 KPI、趋势、热点、竞品、情绪与行动面板。蓝色用于主要数据，绿色与红色用于情绪状态，同时辅以文字标签。截图来自已开发页面，演示品牌与指标仅用于验证布局和交互。')
    paragraph('页面设计将主要指标放在上部，先回答本周表现，再通过趋势和本周结论解释变化。热点与竞品用于内容选择和差异比较，情绪模块用于查看评价点。风险状态不只依赖颜色，还要显示文字与来源；后续点击结论时，应进入相关笔记和评论证据。')
    paragraph('界面保留键盘焦点、模块快捷导航和不同屏宽下的响应式布局。当前 JSON 导出只下载演示快照；周期选择、工作区切换、行动新增和归档入口尚未接入真实持久化数据，应在完成后端后再验证完整流程。')
    paragraph('数据','h1',True)
    paragraph('系统数据包括公开笔记、作者资料、评论与任务日志。原始响应以 JSON 保留，可选 JSONL 落盘；标准化后按 note_id、author_id 和 comment_id 关联，并由品牌和周次生成快照。下表中的字段为归一化目标，具体值以接口实际返回为准。')
    table(['对象','核心字段','分析用途'],[
        ['笔记','主键、标题、正文、发布时间、话题','品牌匹配、热点与内容形态'],
        ['互动','点赞、收藏、评论、分享及采集时间','篇均互动与竞品效率'],
        ['评论','评论主键、笔记主键、内容、时间','情绪、评价维度与证据'],
        ['作者与任务','作者主键、公开统计、任务状态','作者结构、覆盖率与审计'],
    ],[1200,3400,2458],'表1 主要数据对象与用途')
    paragraph('数据示例可表示为：note_id=N001，标题为“秋日通勤拿铁体验”，发布时间为 2026年10月15日，点赞120、收藏30、评论8、分享2，关联评论为“香味不错，但包装容易漏”。该记录是说明字段的合成样例，可同时体现正向口感与负向包装评价，不对应具体用户。')
    paragraph('品牌声量按时间窗内命中品牌词的去重笔记数计算；总互动量为可用点赞、收藏、评论和分享值之和。缺失字段保留缺失标记，并单列完整字段样本上的互动统计；没有曝光字段时，使用互动量除以笔记数作为篇均互动，不把该值称为曝光互动率。')
    paragraph('竞品声量份额按品牌样本声量除以品牌与竞品样本声量之和计算，使用相同时间窗、关键词规则和去重方法。正向情绪率与有效文本数一起展示。文本只提供主观评价和关注度线索，市场空间与增长潜力须结合价格、销售或行业统计等外部资料作进一步判断。')
    paragraph('质量控制从主键去重、发布时间筛选、品牌别名归一和字段缺失记录入手。每份周报保存采集时间、规则版本与样本量；采集失败保留上一版快照，显示数据新鲜度。会话凭据与公开内容分开保存，周报中仅保留分析必需的公开字段及证据索引。')

    # Page 5.
    paragraph('系统涉及的相关智能算法','h1',True)
    paragraph('热点识别与增长分析','h2')
    paragraph('热点识别拟采用 TF-IDF 关键词提取与周度增长分析。首先对标题、正文和话题文本分词，去除停用词和无关符号，将品牌别名映射到标准词；再计算词语在单篇文本中的频率和跨文本的区分能力，形成候选关键词。由品牌词表和人工主题规则把相关词合并为“通勤咖啡”“包装体验”等可解释话题。')
    paragraph('话题排序同时考察本周去重笔记数、较上周变化和篇均互动。环比定义为本周与上周声量之差除以上周声量；上周为零或样本量不足时展示“新增”或“基线不足”，单独列出样本量，避免小基数话题因增长率过高而占据榜首。词频和热度反映讨论关注度，不能直接推导购买意愿或销售增长。')
    paragraph('验证时应人工检查前二十个关键词和话题的相关性，剔除同名词、广告模板和与品牌无关的内容，并比较重复采集对排名的影响。当前算法为设计方案，页面中的热点结果由演示样例提供。')
    paragraph('文本情感与评价点识别','h2')
    paragraph('情感模块拟采用中文预训练语言模型进行正向、中性和负向分类。输入以单条正文或评论为单位，输出类别和置信度；对过短、语义不明、混合观点或低置信文本设置“待复核”，并通过口感、包装、价格、服务等维度词定位具体评价点。文本内容只作为待分析数据，模型结果不直接触发外部操作。')
    paragraph('正向情绪率按有效分类文本中的正向数量占比计算，同时展示有效样本量、待复核比例和模型版本。正文与评论分开统计后再按明确口径汇总，避免热门笔记评论过多导致一类样本完全主导结论。负向率与负向高互动样本用于生成风险候选，最终风险等级应由人工确认。')
    paragraph('后续可人工标注一批文本，采用训练与验证隔离的样本评估准确率、宏平均 F1 和负向召回率，并重点复核反讽、否定和领域用语。目前尚未开展品牌情感模型实测，本作业不报告模型精度或虚构预测结果。')

    # Page 6.
    paragraph('实践','h1',True)
    paragraph('实践从现有小红书数据获取系统出发。首先梳理采集接口、任务配置和平台目录，确认笔记、作者与评论的数据来源；随后将周报需求拆成总览、热点、竞品、情绪、行动和归档模块，设计统一数据快照，使采集与展示通过清晰字段衔接。')
    paragraph('前端使用 HTML、CSS 和 JavaScript 实现门户原型，放置于小红书平台 web/brand-report 目录，由现有 FastAPI 静态挂载提供 /brand-report/ 页面，并在采集工作台增加入口。页面具有模块锚点导航、演示 JSON 下载和运行状态请求；周期选择目前只产生交互提示，尚未加载不同周次的数据。')
    paragraph('随后整理数据需求、框架分层和功能说明，并将图示与当前门户截图填入本课程模板。演示品牌采用 NEO 咖啡，12,480 篇声量和 72.4% 正向情绪率均为页面样例，不构成真实采集结论。')
    paragraph('验证方法与结果','h2')
    table(['验证项目','已记录结果','结论边界'],[
        ['静态路由','页面、CSS 和 JS 的本地 HTTP 请求返回 200','表明资源可加载'],
        ['页面检查','1440px 桌面截图无横向溢出','不代表所有终端均已实测'],
        ['离线回归','此前小红书平台测试 92 项通过','不等于线上采集成功率'],
        ['访问排查','发现 8000 端口未监听后启动原服务','服务需持续运行'],
    ],[1350,3400,2308],'表2 原型阶段的验证记录')
    paragraph('上述结果来自此前开发记录。离线测试使用本地样例，未将测试自动转换成真实采集。浏览器访问问题说明，页面构建成功和本机服务持续运行是两项独立条件，应分别检查静态路由与端口监听。')
    paragraph('当前成果是采集基座之上的门户原型与设计文档。下一步依次实现标准化落库、按周聚合、主题和情感模型、证据下钻、历史归档和完整周报导出。缺失字段保持缺失，会话过期和采集失败显示状态；新增能力均先使用离线样例验证，再按明确任务接入实际数据。')

    # Page 7. Distinguish actual AI use from reconstructed reusable prompts.
    paragraph('AI使用说明','h1',True)
    paragraph('本项目使用 AI 辅助编写 HTML、CSS 和 JavaScript 代码，主要处理指标卡片、响应式布局、按钮事件、接口请求、JSON 下载与键盘操作；调试阶段用于检查静态资源路径、服务端口及语法错误。代码按具体文件和行为逐项修改，再通过本地访问与离线检查验证。')
    paragraph('以下十条提示词根据本次编码任务具体化整理，可直接用于代码修改；它们是任务表述的整理，不是逐条聊天原文。')
    table(['序号','提示词或问题','用途'],[
        ['1','在 web/brand-report/index.html 编写四张指标卡，分别显示声量、互动量、正向率和风险数。','HTML组件'],
        ['2','修改 style.css：用 CSS Grid 排列卡片，700px 以下每行两张，保证页面没有横向溢出。','响应式CSS'],
        ['3','在 app.js 用 fetch 请求 /v1/xhs/runtime，检查 response.ok，并在请求失败时显示离线提示。','接口与异常处理'],
        ['4','为导出按钮绑定事件：将演示周报转为 JSON，用 Blob 和下载链接保存文件，结束后释放 URL。','JSON下载'],
        ['5','根据 data-section 切换导航的 is-active 类，并使用 scrollIntoView 跳到对应内容。','DOM事件处理'],
        ['6','给 week-select 绑定 change 事件，读取所选周次并提示；保留演示数据标识，暂不伪装成真实周报切换。','下拉框事件'],
        ['7','监听数字键1至5跳转模块；焦点在 input、select 或 textarea 内时，跳过快捷键处理。','键盘事件'],
        ['8','复用 FastAPI 静态挂载，检查 /brand-report/、style.css 和 app.js 路径，分别确认返回200。','路由与资源联调'],
        ['9','排查 localhost:8000 访问失败：检查监听端口与进程，启动现有 main.py 后重新请求门户。','Python服务调试'],
        ['10','在正确目录执行 node --check app.js；从小红书平台目录运行 pytest tests -q，核对报错信息。','语法与离线回归'],
    ],[650,4750,1658],'表3 AI辅助写代码的具体提示词')
    paragraph('生成代码通过本地请求、语法检查与离线回归验证。')

    body.append(sect)
    data['word/document.xml']=E.tostring(tree,encoding='UTF-8',xml_declaration=True,standalone=True)
    for i,name in enumerate(['architecture.png','functions.png','portal.png'],1):data[f'word/media/image{i}.png']=(TMP/name).read_bytes()
    settings=E.fromstring(data['word/settings.xml']);prop(settings,'updateFields',val='true')
    data['word/settings.xml']=E.tostring(settings,encoding='UTF-8',xml_declaration=True,standalone=True)
    with ZipFile(OUT,'w',ZIP_DEFLATED) as z:
        for n,b in data.items():z.writestr(n,b)
    changed=[]
    with ZipFile(REF) as r,ZipFile(OUT) as z:
        for n in r.namelist():
            if r.read(n)!=z.read(n):changed.append(n)
    allowed={'word/document.xml','word/settings.xml','word/media/image1.png','word/media/image2.png','word/media/image3.png'}
    assert set(changed)<=allowed,changed
    (TMP/'package-verification.json').write_text(json.dumps({'changed_parts':changed,'reference_sha256':hashlib.sha256(REF.read_bytes()).hexdigest(),'output':str(OUT)},indent=2,ensure_ascii=False),encoding='utf-8')
    print(OUT)

if __name__=='__main__':
    digest=hashlib.sha256(REF.read_bytes()).hexdigest()
    contract=f'''# Template execution contract
Reference: {REF}; SHA256 {digest}. Reference rendered as four pages, one A4 portrait section.
Evidence: reference/page-1.png through page-4.png; template-style-evidence.json.
Geometry: 11906 x 16838 twips; margins top/bottom 1440, left/right 1800; header 851, footer 992. Single column.
Preserve all section XML, styles.xml, numbering.xml, theme, font table, header1.xml and footer1.xml, customXml and relationships byte for byte.
Typography: template title centered 22 pt bold Song; name centered 14 pt bold; Heading 2 18 pt bold with numId 1 ilvl 0; Heading 3 16 pt bold with numId 1 ilvl 1. Use original real styles.
Body according to template requirement: Song 12 pt, 1.25 line spacing, 2-character first-line indent, zero paragraph spacing; no empty body paragraphs. Table body 10.5 pt Song, single line spacing. Centered captions 10.5 pt.
Recurring elements: original Beijing University of Civil Engineering and Architecture header and centered PAGE footer field preserved. Settings updateFields=true for Word page-field refresh.
Slots: body paragraphs 0 title, 1 identity, 2-7 background, 8-20 architecture/functions/portal, 22-23 data, 24-25 algorithms, 26-27 practice, 28-30 AI use. Expand by cloning source paragraph roles; retain six main numbered sections.
Replace figure payloads image1.png,image2.png,image3.png with project architecture, functional tree and actual local portal screenshot; resize corresponding inline extents and caption. Keep relationships and image4.png intact.
Remove formatting-instruction section 31-39 and reminder 40, including example table and image anchor. Replace their content by real project tables cloned from the source table format.
Data claims: distinguish existing collector and static portal from proposed sentiment, topic, archive, market opportunity and export modules. Label all UI examples as demo. Do not invent runtime measurements or model accuracy.
Page budget: eight content pages within template six-to-eight requirement, controlled section/subsection starts. Personal data from user: 李昊阅 202409010201.
QA: render all reference/final pages; inspect figures and typography, retain exact section geometry, compare all package parts and allow changes only in document.xml, settings.xml, image1-3 PNG. Reference file remains unchanged.
'''
    (TMP/'artifact.md').write_text(contract,encoding='utf-8')
    if not (TMP/'portal.png').exists():asyncio.run(portal())
    architecture();functions();build()
