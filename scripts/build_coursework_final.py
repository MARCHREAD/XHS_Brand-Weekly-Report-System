"""Create the final course assignment from the user's original retained template."""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=Path('A:/download/智慧城市技术概论 大作业模板.docx')
TMP=ROOT/'output/coursework-final-20261102'
ASSETS=ROOT/'docs/assets/coursework-final'
OUTPUT=ROOT/'docs/李昊阅_202409010201_智慧城市技术概论大作业最终版.docx'
OLD_ASSETS=ROOT/'docs/assets/algorithm-implementation'


def diagrams():
    def font(size,bold=False):
        return ImageFont.truetype('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',size)
    def text(draw,body,x,y,size=28,bold=False,color='#203047'):
        draw.multiline_text((x,y),body,font=font(size,bold),fill=color,anchor='mm',align='center',spacing=13)
    im=Image.new('RGB',(1800,1050),'white');d=ImageDraw.Draw(im)
    rows=[('应用层','品牌周报门户  热点与竞品  情绪与评价','品牌和周次筛选  原文下钻  快照归档  JSON导出'),
          ('平台层','SQLite数据存储  文本清洗  品牌归因','BERTopic话题发现  LinearSVC情感分类  周次指标聚合'),
          ('网络层','HTTPS内容请求  本地FastAPI服务','任务调度  游标分页  暂停续采  会话与限流状态'),
          ('感知与采集层','公开笔记标题和正文  主评论及随页回复','发布时间  点赞收藏评论分享  采集时间和质量记录')]
    for i,(name,line1,line2) in enumerate(rows):
        y=65+i*215
        d.rounded_rectangle((180,y,1620,y+165),radius=12,fill=['#EAF1FB','#EDF5F0','#FFF4E6','#EFF3F8'][i],outline='#6B819C',width=3)
        d.line((465,y+18,465,y+147),fill='#9EADBF',width=2)
        text(d,name,320,y+83,34,True)
        text(d,line1,1040,y+53,30,True)
        text(d,line2,1040,y+112,27)
        if i<3:
            d.line((900,y+205,900,y+174),fill='#557595',width=4)
            d.polygon([(900,y+168),(888,y+183),(912,y+183)],fill='#557595')
    for x,label in [(76,'数据质量与溯源'),(1724,'会话隔离与访问控制')]:
        d.rounded_rectangle((x-48,65,x+48,875),radius=10,fill='#F6F8FA',outline='#9EADBF',width=2)
        text(d,'\n'.join(label),x,470,30,True)
    text(d,'以公开数字内容为感知对象  数据自下而上汇聚并形成可核查的分析结果',900,989,27)
    im.save(ASSETS/'architecture.png')
    im=Image.new('RGB',(1800,1000),'white');d=ImageDraw.Draw(im)
    d.rounded_rectangle((450,35,1350,150),radius=12,fill='#EAF1FB',outline='#6B819C',width=3)
    text(d,'品牌营销可视化周报系统',900,93,37,True)
    centers=[235,675,1115,1555]
    groups=[('数据管理',['品牌与竞品配置','采集与断点续采','去重和覆盖检查']),
            ('营销分析',['BERTopic话题','趋势与竞品对标','原文证据查看']),
            ('情绪与评价',['LinearSVC分类','评价维度归纳','负向候选复核']),
            ('周报应用',['门户与范围筛选','快照归档与导出','行动状态记录'])]
    d.line((900,150,900,220),fill='#6B819C',width=4);d.line((235,220,1555,220),fill='#6B819C',width=4)
    for cx,(name,leaves) in zip(centers,groups):
        d.line((cx,220,cx,270),fill='#6B819C',width=4)
        d.rounded_rectangle((cx-190,270,cx+190,375),radius=10,fill='#EDF2F8',outline='#6B819C',width=3)
        text(d,name,cx,323,34,True)
        for j,label in enumerate(leaves):
            y=425+j*145
            d.line((cx,y-50,cx,y),fill='#8FA2B6',width=3)
            d.rounded_rectangle((cx-190,y,cx+190,y+105),radius=10,fill='white',outline='#8FA2B6',width=2)
            text(d,label,cx,y+53,28)
    d.rectangle((90,906,1710,979),fill='#F6F8FA',outline='#A9B7C7',width=2)
    text(d,'人工复核贯穿话题解释与情感评价  市场规模和增长预测仍需外部数据及历史基线',900,943,26)
    im.save(ASSETS/'functions.png')


def build():
    TMP.mkdir(parents=True,exist_ok=True);ASSETS.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    assert digest=='81af1ff2217c785617f1f0bae9005968e40b5ad3027c014133cbff2ad350d07f'
    (TMP/'artifact.md').write_text(f'''# Final assignment template execution contract
Reference {REFERENCE}; SHA256 {digest}. Previously rendered original: output/algorithm-implementation-20261026/reference/page-1.png through page-4.png.
One A4 portrait section, 11906 by 16838 twips; top/bottom margins1440; left/right1800; header851, footer992. Preserve section XML.
Use original Heading2 and Heading3 roles, source direct numbering numId1 levels0/1. Title22pt bold Song; identity14pt bold Song; main heading18pt, subheading16pt. Body Song12pt, line1.25, firstLine480 twips and firstLineChars200, zero paragraph spacing, snapToGrid0. Caption10.5pt centered; tables10.5pt single spacing.
Six main sections: background; system framework with overall framework, functional structure, portal; data; two concrete algorithms; implementation; AI coding use with at least10 concrete prompts. Preserve original academic header and PAGE footer and all styles/numbering/theme/customXml.
Source slots body0:title,1:identity,2:background,3:problem,5:overview,8:framework,9:overall diagram,13:functions,17:portal,22:data,24:algorithm,26:practice,28:AI use. Clone source paragraph patterns and expand content. Remove red instructional examples and sections31-40.
User's latest requirement supersedes original6-8 page hint: final6-10 pages inclusive. Target10 pages, explicit major content breaks without empty body paragraphs.
Page sequence:1 background;2 framework;3 functions;4 portal;5 data;6 BERTopic;7 LinearSVC;8 actual IDE implementation;9 validation;10 AI coding prompts.
Figures: refreshed system framework and functional structure, actual archived portal, two native IDE screenshots, actual model dashboard. Captions centered and image width5.2in, about90% text area. Original screenshot provenance October26, no new measurement claims.
Editable package parts document.xml, document.xml.rels, settings.xml, core metadata, app page-count metadata and added PNGs. Append only missing Title style; original style nodes stay identical. Preserve all other original package members and original image relationships.
All numeric results from verified October26 artifacts. Partial collection disclosed. No unsupported market size, growth, prediction accuracy or business uplift claims.
AI-use section strictly describes code assistance and concrete coding prompts; omit AI architecture, functional diagram or Word writing assertions.
Verify package preservation, body paragraph formatting, names, six main headings, image relationships, no instruction leftovers and10 coding prompts. Render every final page and inspect at100percent. Original unchanged.
''',encoding='utf-8')
    diagrams()
    source=Document(REFERENCE);prototypes=list(source.paragraphs)
    doc=Document(REFERENCE)
    if 'Title' not in doc.styles:
        doc.styles.add_style('Title',WD_STYLE_TYPE.PARAGRAPH).base_style=doc.styles['Normal']
    for el in list(doc._element.body):
        if el.tag!=qn('w:sectPr'):doc._element.body.remove(el)
    # Reuse the previously validated table and native equation helpers.
    tree=ast.parse((ROOT/'scripts/build_algorithm_implementation_doc.py').read_text(encoding='utf-8'))
    method=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    helpers=[n for n in method.body if isinstance(n,ast.FunctionDef) and n.name in {'table','math'}]
    namespace=dict(globals(),doc=doc,re=__import__('re'))

    def p(text,role='body',new_page=False):
        para=doc.add_paragraph(style={'title':'Title','name':'Normal','h1':'Heading 2','h2':'Heading 3','body':'Normal','caption':'Normal'}[role])
        proto=prototypes[{'title':0,'name':1,'h1':2,'h2':3,'body':4,'caption':11}[role]]._p.pPr
        if para._p.pPr is not None:para._p.remove(para._p.pPr)
        if proto is not None:para._p.insert(0,deepcopy(proto))
        para.style={'title':'Title','name':'Normal','h1':'Heading 2','h2':'Heading 3','body':'Normal','caption':'Normal'}[role]
        pr=para._p.get_or_add_pPr()
        for key in ['rPr','pBdr']:
            el=pr.find(qn('w:'+key))
            if el is not None:pr.remove(el)
        if role not in {'h1','h2'}:
            el=pr.find(qn('w:numPr'))
            if el is not None:pr.remove(el)
            np=OxmlElement('w:numPr');ni=OxmlElement('w:numId');ni.set(qn('w:val'),'0');np.append(ni);pr.append(np)
        fmt=para.paragraph_format;fmt.page_break_before=new_page;fmt.keep_with_next=role in {'h1','h2','title'};fmt.keep_together=True
        fmt.line_spacing=1.25 if role=='body' else 1
        fmt.space_before=Pt(0 if role in {'body','title','name'} else 6);fmt.space_after=Pt(0 if role=='body' else 6)
        fmt.first_line_indent=Pt(24 if role=='body' else 0)
        ind=pr.find(qn('w:ind'))
        if ind is not None:ind.set(qn('w:firstLineChars'),'200' if role=='body' else '0')
        snap=pr.find(qn('w:snapToGrid'))
        if snap is None:snap=OxmlElement('w:snapToGrid');pr.append(snap)
        snap.set(qn('w:val'),'0')
        para.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY if role=='body' else WD_ALIGN_PARAGRAPH.LEFT if role in {'h1','h2'} else WD_ALIGN_PARAGRAPH.CENTER
        run=para.add_run(text);run.font.name='宋体';run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体')
        run.font.size=Pt({'title':22,'name':14,'h1':18,'h2':16,'body':12,'caption':10.5}[role]);run.font.bold=role in {'title','name','h1','h2'};run.font.color.rgb=RGBColor(0,0,0)
        return para
    namespace['p']=p
    exec(compile(ast.Module(body=helpers,type_ignores=[]),'<validated-document-helpers>','exec'),namespace)
    table,math=namespace['table'],namespace['math']
    def fig(path,caption,width=5.2):
        para=p('','caption');para.paragraph_format.keep_with_next=True
        para.add_run().add_picture(str(path),width=Inches(width))
        for el in para._p.xpath('.//wp:docPr'):el.set('descr',caption)
        p(caption,'caption')

    # Page1. No separate cover page; retain the template's combined title/background.
    p('基于逆向小红书数据的品牌营销\n可视化周报系统设计与实现','title')
    p('姓名：李昊阅      学号：202409010201','name')
    p('背景','h1');p('问题描述','h2')
    p('小红书中大量笔记和评论记录了用户对产品、创作工具和消费体验的讨论。品牌运营人员需要了解近期关注点、竞品表现及用户评价，但手工检索和逐条整理耗时较长。同一话题可能分散在多篇笔记中，热门笔记的高互动量也容易掩盖其他反馈；仅查看搜索结果和累计点赞，难以直接形成结构清晰、来源可查的周报。')
    p('本项目已有小红书数据采集工作台，能够获取公开笔记及评论。实践中发现，取得数据之后仍需完成品牌归因、时间筛选、话题汇总和情感判断。因此，本系统在现有采集基座上增加分析与展示能力，以固定品牌和周次组织数据，减少重复整理，辅助运营人员选题、比较竞品及复核负向评价。')
    p('系统概述','h2')
    p('本系统面向品牌市场、内容运营与数据分析人员，基于现有小红书公开数据采集工作台，构建品牌营销可视化周报。系统以 libtv 为主推品，以即梦、updream 为竞品，组织笔记标题、正文、评论、发布时间及互动指标，经过主键去重、文本清洗、品牌匹配和周次筛选后，形成统一分析结果。BERTopic 用于发现相近讨论话题，LinearSVC 用于评论情感三分类，门户通过指标卡、趋势图、话题表、竞品条形图和情绪环图展示结果，并支持原文查看、人工标注、结果导出与历史快照。当前已完成数据落库、算法接入和门户联调；采集覆盖与负向识别仍需完善，市场空间和增长潜力主要作为后续结合外部数据的分析方向。')
    p('系统的智慧性体现在自动归纳讨论主题、初筛评论情绪，并将结果与原文证据关联。数据支持运营判断，尚未建立销售或曝光预测模型。本作业使用真实样本和已保存的验证记录说明实现效果，结果中的不确定性通过样本范围、模型指标及待复核状态体现。')

    # Page2. Course-style four-layer conceptual model.
    p('系统框架','h1',True);p('整体框架图','h2')
    fig(ASSETS/'architecture.png','图1 系统整体框架图')
    p('系统采用感知与采集层、网络层、平台层和应用层四层组织方式。感知对象为公开数字内容，使用既有软件接口完成信息获取；四层结构用于说明内容从获取、传输到计算和应用的关系。')
    p('感知与采集层：按主推品和竞品关键词发现公开笔记，获取标题、正文、时间和互动字段，并补充主评论及随页回复。逐页保存笔记、评论主键和采集状态，形成后续分析的数据基础。')
    p('网络层：通过 HTTPS 请求公开内容服务，以本地 FastAPI 向门户提供接口。任务管理负责排队、分页、断点和会话状态；出现限流或验证要求时保留已有进度，等待处理后续采。')
    p('平台层：SQLite 保存记录，清洗模块执行去重、有效文本筛选和品牌归因，分析模块运行 BERTopic 与 LinearSVC，再按品牌和日期汇总指标。模型版本、预测结果及周报快照保持关联。')
    p('应用层：信息门户集中展示品牌表现、热点话题、竞品对比和用户情绪，提供筛选、原文查看、标注与导出入口。数据质量和来源记录贯穿各层，账号会话与分析材料分开保存。')

    # Page3. Final implemented capabilities, no outdated design-only banners.
    p('系统功能','h2',True)
    fig(ASSETS/'functions.png','图2 系统功能结构图')
    p('数据管理模块配置主推品、竞品和报告时间窗，查看搜索页数、笔记数量、评论数量及任务状态。采集逐页落盘并支持暂停续采；去重和覆盖检查用于区分已发现记录、详情完整记录和达到当前采样目标的记录。')
    p('营销分析模块将 BERTopic 聚类形成的话题按文本量呈现，结合发布日期展示讨论变化。竞品对标采用统一时间窗比较样本笔记数和累计互动量，帮助用户发现相对关注度差异；点击话题可查看关键词及关联文本。')
    p('情绪与评价模块使用 LinearSVC 识别正向、中性和负向评论，对分类分数接近的内容标为待复核。价格与积分、生成效果、学习与创作、使用体验等维度由关键词规则辅助归类，负向集中话题进入人工复核候选。')
    p('周报应用模块提供统一门户、品牌与周期筛选、历史快照及 JSON 导出，便于复盘和资料留存。行动项完成状态在浏览器本地保存；采集与标注工作台支持补充数据和人工评论标签，再生成更新后的分析快照。')
    p('当前系统提供的是讨论样本分析。市场空间与增长潜力可从需求主题和竞品差异中寻找线索，但销售规模、真实市场份额和增长预测还需要外部交易数据、曝光数据及连续历史基线。')

    # Page4. Explain functions rather than narrating individual screenshot numbers.
    p('管理一张图','h2',True)
    fig(OLD_ASSETS/'real-dashboard.png','图3 品牌周报信息门户真实运行界面')
    p('门户采用左侧导航与右侧工作区。用户可选择研究品牌、报告周期及本期或全部样本范围。指标卡展示品牌声量、互动表现、正向情绪率与负向话题候选；趋势图观察讨论分布，话题表归纳关注焦点，竞品条形图比较同窗样本表现。')
    p('情绪环图呈现正向、中性和负向评论比例，待复核评论单列；评价维度帮助定位价格、生成效果及使用体验问题。原文入口支持追溯分析证据，模型验证区展示样本量、标签来源和分类指标，归档及导出用于保存阶段成果。截图记录于 2026 年 10 月 26 日，图中数值对应当时的样本与模型快照。')

    # Page5. Data objects, meaningful example and coverage limits.
    p('数据','h1',True)
    p('数据来自现有小红书采集工作台的公开笔记与评论接口，按 libtv、即梦和 updream 三组关键词组织任务。原始响应为 JSON，标准化记录以 JSON 字段存入 SQLite，按笔记与评论主键关联；清洗文本、模型预测及报告快照分别保存。')
    p('表1 主要数据对象及分析用途','caption')
    table(['数据对象','主要字段','用途'],[
        ['笔记','ID、标题、正文、发布时间','品牌匹配与话题发现'],
        ['互动指标','点赞、收藏、评论、分享','累计互动与竞品对比'],
        ['评论','评论ID、笔记ID、内容、时间','情感分类与原文证据'],
        ['任务记录','关键词、排序、页数、游标','断点续采与覆盖检查'],
        ['模型与周报','话题、情感、版本、生成时间','分析展示与历史归档'],
    ],[1.0,2.4,1.8])
    p('字段示例：note_id=N001，title=“libtv 视频生成体验”；comment_id=C001，content=“效果不错，但积分消耗偏高”。该示意用于解释数据结构，也说明混合评价需结合语境分析。')
    p('每个关键词目标为 100 个非空搜索结果页。平台在单一排序提前结束时，采集器按其他排序补采并按笔记主键合并；有效页是跨排序请求量，不等于互不重复的页面。评论现采用每篇前两页主评论及随页回复，保留调整前更深覆盖的记录。')
    p('2026 年 10 月 26 日 21:24 的复核记录显示，任务发现 3,850 篇去重笔记，保存 7,800 条评论，301 篇达到当前详情与评论采样目标，整体仍为部分完成。BERTopic 实际输入为 1,737 条品牌相关文本，SVM 有效标签为 253 条；模型使用量与采集总量分别统计。')
    p('清洗去除链接、表情标记、重复文本、短文本及订阅提醒。品牌按标题与正文名称匹配，评论沿所属讨论串归因，多品牌记录可重复归属。日期与互动缺失保持缺失，声量按发布日期统计，互动为采集时累计快照；缺少历史基线时不计算新增互动或环比。')
    p('样本份额不代表平台总体市场份额。原始数据、账号会话和模型文件保存在本地，公开仓库只保留源码、材料及汇总结果。')

    # Page6. First concrete algorithm.
    p('系统涉及的相关智能算法','h1',True);p('BERTopic 热点话题发现','h2')
    p('话题发现使用 BERTopic，语义编码器选用多语言 MiniLM，具体型号为 paraphrase-multilingual-MiniLM-L12-v2。算法处理品牌相关的标题、正文和评论，以语义向量、降维、密度聚类及类别词权重组成管线，输出话题归属、关键词和文本数量。')
    p('首先，MiniLM 把每条文本映射为 384 维向量并进行 L2 归一化，使语义接近的文本在向量空间中相邻。编码器使用预训练权重，项目不对其进行微调；后续拟合降维、聚类和话题表示组件。')
    math('cos(eᵢ, eⱼ) = (eᵢ · eⱼ) / (‖eᵢ‖₂ ‖eⱼ‖₂)')
    p('其次，UMAP 依据高维近邻图优化低维表示，尽量保留局部相似关系。本次由 384 维降至 5 维，设置 n_neighbors=15、min_dist=0、metric=cosine 和 random_state=42，以减少后续聚类的计算负担。')
    p('随后，HDBSCAN 根据核心距离和互达距离构造密度层次，选取稳定簇，将难归类的低密度文本标为 -1。该方法无需事先指定话题数。本次 min_cluster_size=30、min_samples=3，使用欧氏距离。')
    p('最后，将同簇文本合并为类别文档，使用 jieba 分词并过滤停用词、无效符号及品牌词，再通过 c-TF-IDF 为词语赋权。词在本簇出现较多而在其他簇区分度较高时，能成为该话题的代表关键词。')
    math('w(t,c) = (f(t,c) / Σᵤ f(u,c)) × ln(1 + A / Σᵥ f(t,v))')
    p('式中 f(t,c) 为词 t 在话题 c 中的频数，A 为各话题合并文档的平均总词数。模型保留高分关键词并关联原文，可辅助识别积分、会员或创作需求等讨论方向。跨次重训的话题编号可能变化，应对齐含义后再比较。')
    p('本次对 1,737 条输入清洗去重后保留 1,058 条有效文本，形成 6 个话题、99 条噪声。泛互动话题占比较高，话题数量不等于有效营销热点数；当前未建立人工话题真值集，结果主要用于自动归纳与人工解释。')

    # Page7. Second concrete algorithm and actual evaluation.
    p('LinearSVC 评论情感分类','h2',True)
    p('情感分类采用 scikit-learn 的 LinearSVC，即线性支持向量机。输入为带正向、中性或负向标签的单条评论，特征由字符 TF-IDF 和固定 MiniLM 语义向量拼接构成。字符片段保留局部表达，语义向量补充句子含义。')
    p('TF-IDF 通过词频与逆文档频率突出有区分能力的字符片段，本次选中 2 至 4 gram，最多保留 60,000 个特征，启用 sublinear_tf 并归一化。词表和权重仅在训练部分拟合，测试部分不参与特征学习。')
    math('x = [ TFIDF₂₋₄(text) ; 0.5 × MiniLM(text) ]')
    p('LinearSVC 为每个类别学习线性超平面，以较大的分类间隔区分样本，同时允许一定误分损失。三个类别采用一对其余策略，使用 L2 正则化和平方铰链损失。')
    math('min  ½‖w‖₂² + C Σᵢ αᵧᵢ [max(0, 1 − yᵢ(w·xᵢ+b))]²')
    p('上式为二分类子问题的核心目标，C 调节复杂度与误分损失，α 表示类别权重。本次 class_weight=balanced、C=1.0、max_iter=10000。参数通过训练内部三折分组交叉验证选择，以宏平均 F1 为指标。')
    p('样本按笔记分组，固定测试评论所属整篇笔记与训练部分隔离。253 条有效标签中，205 条用于评估模型训练，29 条用于固定测试，19 条来自保留笔记但不计入测试。评估分类器单独保存，生产分类器再用全部标签重拟合。')
    p('预测时取 decision_function 分数最高的类别，最高与次高分差小于 0.2 时转为待复核，分差不解释为概率。分类结果用于情绪分布和负向候选初筛，具体评价维度另由关键词规则归纳。')
    p('固定测试准确率为 89.66%，宏平均 F1 为 0.6050，负向召回率为 0。标签中人工复核 86 条、辅助标注 167 条，测试集 29 条全部为辅助标签，独立人工评测仍需补充。模型已完成训练和加载验证，负向识别能力尚不足以单独支持舆情判断。')

    # Page8. Two actual native IDE screenshots, concise process without pasted code blocks.
    p('实践','h1',True);p('开发环境与核心实现','h2')
    p('开发采用 Windows、VS Code 和 Python 3.13。FastAPI 提供接口，SQLite 保存断点，前端使用 HTML、CSS、JavaScript。以下为 2026 年 10 月 26 日留存的实际开发截图。')
    fig(OLD_ASSETS/'dev-bertopic.png','图4 VS Code 中的 BERTopic 管线实现与运行终端')
    p('topics.py 完成语义编码、聚类与话题词输出，保存后加载完整管线执行 transform。后端按周次筛选文本，再返回对应指标。')
    fig(OLD_ASSETS/'dev-svm.png','图5 VS Code 中的 LinearSVC 实现与固定测试复现')
    p('情感模块构造特征并完成分组评估，复核脚本重载模型复算固定测试集。前端通过 fetch 获取结果，使用 SVG 和 CSS 绘制图表，连接原文、快照与导出功能。')

    # Page9. Display evidence and exact metric interpretation.
    p('实现验证与结果分析','h2',True)
    fig(OLD_ASSETS/'model-dashboard.png','图6 门户中的模型验证结果与混淆矩阵')
    p('2026 年 10 月 26 日 21:24，离线复核脚本重新加载已保存的评估分类器和生产模型，检查文件 SHA-256，复算固定测试结果，并对 BERTopic 保存向量执行预测。加载和结果复现检查通过，过程仅使用本地数据，不触发采集或训练。')
    p('表2 固定测试集分类结果','caption')
    table(['指标','结果','解释'],[
        ['准确率','89.66%','29 条中正确 26 条'],
        ['宏平均 F1','0.6050','三类识别效果等权衡量'],
        ['负向召回率','0.00%','2 条负向均被判为中性'],
        ['中性召回率','100.00%','8 条中性均被识别'],
        ['正向召回率','94.74%','19 条正向中识别 18 条'],
    ],[1.25,1.0,2.95])
    p('此前 23 项周报离线测试及 JavaScript 语法检查通过，浏览器已检查筛选、原文查看、JSON 导出和归档交互。模型测试结果表明总体准确率会受到正向样本较多的影响，因此门户同时呈现宏平均 F1、每类召回率和标签来源。')
    p('本阶段完成了采集记录落库、智能分析及主要可视化功能。当前采集仍为部分完成，样本覆盖不一致，负向测试规模小；下一步补充独立人工标签、减少泛互动噪声，再随采集进展更新模型。现阶段未测量节省工时或营销收益，不报告相关提升比例。')

    # Page10. User-requested AI-use scope only: coding prompts.
    p('AI使用说明','h1',True)
    p('项目使用 AI 辅助编写与调试 Python、HTML、CSS 和 JavaScript 代码，重点处理数据接口、分页断点、图表渲染、算法管线和离线验证。代码结合项目已有文件逐项修改，再通过本地运行、测试和真实数据检查验证；模型训练及复核均由本地程序执行。')
    p('以下提示词根据本次实际编码任务整理为可复用表述，明确文件、处理规则和验证目标，不作为逐条聊天原文引用。')
    p('表3 AI辅助编程的具体提示词','caption')
    table(['序号','具体提示词或问题'],[
        ['1','在 FastAPI 增加周报接口，支持品牌、七天日期范围和历史样本筛选，缺失字段保留为空。'],
        ['2','修改采集器：每页保存 SQLite 断点，按 note_id 和 comment_id 去重，续采时恢复原游标。'],
        ['3','将每篇主评论上限设为两页，保留随页回复和已采数据，区分采样达标与全部评论结束。'],
        ['4','为 dashboard.js 编写 fetch 异常处理，请求失败显示状态，保持已保存分析结果可识别。'],
        ['5','用 SVG 绘制双纵轴趋势图，蓝线为发文数，橙线为采集时累计互动，缺失值断开。'],
        ['6','用 CSS conic-gradient 绘制正中负情绪环图，待复核另列，正向率只使用已判定样本。'],
        ['7','编写 BERTopic 管线：固定 MiniLM，连接 UMAP、HDBSCAN、中文分词和 c-TF-IDF。'],
        ['8','用字符 TF-IDF 和固定语义向量训练 LinearSVC，按笔记分组隔离测试，训练内部交叉验证选参。'],
        ['9','增加模型复核脚本，重载保存文件，复算固定测试指标、混淆矩阵，并检查模型哈希。'],
        ['10','为品牌筛选、原文弹窗、JSON 导出和快照读取补充离线测试，测试过程保持零真实采集。'],
    ],[.45,4.75])
    p('对生成代码的检查包括输入边界、断点去重、模型保存加载、训练测试隔离和界面交互。模型标签来源单独记录，辅助标签与人工标签分别统计。发现的问题保留到评测和页面中展示，后续依据独立人工样本继续改进。')

    update=doc.settings.element.find(qn('w:updateFields'))
    if update is None:update=OxmlElement('w:updateFields');doc.settings.element.append(update)
    update.set(qn('w:val'),'true');doc.core_properties.title='基于逆向小红书数据的品牌营销可视化周报系统设计与实现';doc.core_properties.author='李昊阅'
    stream=BytesIO();doc.save(stream)
    with ZipFile(REFERENCE) as z:original={n:z.read(n) for n in z.namelist()}
    with ZipFile(BytesIO(stream.getvalue())) as z:generated={n:z.read(n) for n in z.namelist()}
    final=dict(original);allowed={'word/document.xml','word/_rels/document.xml.rels','word/settings.xml','docProps/core.xml','word/styles.xml','docProps/app.xml'}
    for name,data in generated.items():
        if name in allowed or name not in original:final[name]=data
    old_styles=etree.fromstring(original['word/styles.xml']);new_styles=etree.fromstring(generated['word/styles.xml'])
    ids={n.get(qn('w:styleId')) for n in old_styles.findall(qn('w:style'))}
    for node in new_styles.findall(qn('w:style')):
        if node.get(qn('w:styleId')) not in ids:
            assert node.get(qn('w:styleId'))=='Title';old_styles.append(deepcopy(node))
    final['word/styles.xml']=etree.tostring(old_styles,encoding='UTF-8',xml_declaration=True,standalone=True)
    # Existing relationship entries are immutable; append new image references only.
    old_rels=etree.fromstring(original['word/_rels/document.xml.rels']);new_rels=etree.fromstring(generated['word/_rels/document.xml.rels'])
    ids={n.get('Id') for n in old_rels}
    for node in new_rels:
        if node.get('Id') not in ids:old_rels.append(deepcopy(node))
    final['word/_rels/document.xml.rels']=etree.tostring(old_rels,encoding='UTF-8',xml_declaration=True,standalone=True)
    app=etree.fromstring(original['docProps/app.xml'])
    app.find('{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Pages').text='10'
    final['docProps/app.xml']=etree.tostring(app,encoding='UTF-8',xml_declaration=True,standalone=True)
    with ZipFile(OUTPUT,'w',ZIP_DEFLATED) as z:
        for name,data in final.items():z.writestr(name,data)
    assert all(final[n]==data for n,data in original.items() if n not in allowed)
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest()==digest
    (TMP/'package-verification.json').write_text(json.dumps({'reference_sha256':digest,'output':str(OUTPUT),'changed_original_parts':[n for n in original if original[n]!=final[n]],'figures':6,'tables':3,'coding_prompts':10},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUTPUT)


if __name__=='__main__':build()
