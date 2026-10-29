"""Create the implementation chapter from the existing course-style document."""
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=ROOT/'docs/李昊阅_202409010201_智能算法原理与实现.docx'
OUTPUT=ROOT/'docs/李昊阅_202409010201_系统部分实践与开发截图.docx'
TMP=ROOT/'output/system-practice-20261029'
ASSETS=ROOT/'docs/assets/algorithm-implementation'


def build():
    TMP.mkdir(parents=True,exist_ok=True)
    source_hash=hashlib.sha256(REFERENCE.read_bytes()).hexdigest()
    (TMP/'artifact.md').write_text(f'''# Practice chapter template contract
Reference: {REFERENCE}; SHA256: {source_hash}.
Reference uses the retained course template. Existing verified renders: output/algorithm-implementation-20261026/final-v2/page-1.png through page-7.png.
Retain original A4 portrait geometry, margins, existing styles and numbering, header and footer, theme and other opaque package parts.
Use source Title, Heading 2, Heading 3 and Normal roles. Title black 22pt Song, identity black 14pt Song; headings black 16pt; body Song 12pt, line spacing1.25, two-character first-line indent.
Five practice pages: environment and working portal; visualization implementation; BERTopic source and process; SVM source and process; validation and model result page.
Replace body content and add screenshot image relationships. Preserve all other package parts byte-for-byte except document.xml, document.xml.rels, settings.xml and core metadata.
Use original archived VS Code and live dashboard captures dated October26. No newly collected data or live-service availability claim. Presentation metrics come from the verified October26 model snapshot.
Preserve reference file. Render final pages and inspect each page before delivery.
''',encoding='utf-8')
    doc=Document(REFERENCE)
    for el in list(doc._element.body):
        if el.tag!=qn('w:sectPr'):doc._element.body.remove(el)

    def p(text,kind='body',page=False):
        para=doc.add_paragraph(style={'body':'Normal','title':'Title','name':'Normal','h':'Heading 3','caption':'Normal'}[kind])
        f=para.paragraph_format
        f.page_break_before=page;f.keep_together=True;f.keep_with_next=kind in {'title','h'}
        f.line_spacing=1.25 if kind=='body' else 1
        f.space_before=Pt(0 if kind=='body' else 5);f.space_after=Pt(0 if kind=='body' else 6)
        f.first_line_indent=Pt(24 if kind=='body' else 0)
        para.alignment=WD_ALIGN_PARAGRAPH.JUSTIFY if kind=='body' else WD_ALIGN_PARAGRAPH.LEFT if kind=='h' else WD_ALIGN_PARAGRAPH.CENTER
        pr=para._p.get_or_add_pPr()
        snap=OxmlElement('w:snapToGrid');snap.set(qn('w:val'),'0');pr.append(snap)
        np=OxmlElement('w:numPr');num=OxmlElement('w:numId');num.set(qn('w:val'),'0');np.append(num);pr.append(np)
        r=para.add_run(text);r.font.name='宋体';r._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'宋体')
        r.font.size=Pt({'body':12,'title':22,'name':14,'h':16,'caption':10.5}[kind])
        r.font.bold=kind in {'title','name','h'};r.font.color.rgb=RGBColor(0,0,0)
        return para

    def fig(path,caption,width=5.2):
        para=p('','caption');para.paragraph_format.keep_with_next=True
        para.add_run().add_picture(str(path),width=Inches(width))
        for el in para._p.xpath('.//wp:docPr'):el.set('descr',caption)
        p(caption,'caption')

    p('小红书品牌营销周报系统\n部分实践与开发实现','title')
    p('姓名：李昊阅    学号：202409010201','name')
    p('一 实践内容与开发环境','h')
    p('本阶段基于已有的小红书采集工作台，完成品牌周报的数据可视化、BERTopic 话题发现和 LinearSVC 情感分类接入。实践围绕数据读取、指标计算、模型运行和页面展示展开，形成从笔记与评论到分析结果的完整处理流程。')
    p('开发采用 Windows、VS Code 和 Python 3.13，后端使用 FastAPI 与 SQLite，前端使用 HTML、CSS、JavaScript。算法在独立虚拟环境中运行，主要依赖为 BERTopic 0.17.4 和 scikit-learn 1.7.2。')
    fig(ASSETS/'real-dashboard.png','图1 已实现的品牌周报信息门户')
    p('门户提供品牌与周期筛选、指标卡、趋势图、话题排行、竞品比较及情绪分析，并支持原文查看、结果导出与历史快照。本材料采用 2026 年 10 月 26 日留存的真实运行截图，图中数值用于展示当时的系统状态。')

    p('二 主要数据可视化实现','h',True)
    p('可视化模块先由后端按品牌、报告周次或全部样本范围筛选数据，再形成统一结果对象。前端通过 fetch 请求周报接口，将返回的 kpis、trend、topics、competitors 和 sentiment 数据分别交给对应的渲染函数，保证指标和图表使用相同的统计范围。')
    compare=Path('C:/Users/20240/Documents/WeChat Files/wxid_8ejhdjs9bhy012/FileStorage/Temp/14e9f8b7f2fb8c505409c3a78386af4.png')
    if compare.exists():
        figure_path=TMP/'visualization-panels.png';figure_path.write_bytes(compare.read_bytes())
    else:
        figure_path=ASSETS/'real-dashboard.png'
    fig(figure_path,'图2 品牌趋势 热点话题与竞品比较的可视化结果')
    p('品牌趋势通过 SVG 绘制折线和数据点，按发布日期聚合笔记数量，并设置两个纵轴分别表示声量与互动量。页面显示的互动量为对应笔记在采集时的累计值，便于观察高互动内容的时间分布。字段缺失时保持缺失状态，图表不会以零值补齐。')
    p('热点话题以表格展示关键词、关联文本量、笔记数量和情绪倾向；竞品模块通过条形图比较同一时间范围内的样本声量份额。情绪模块采用 CSS conic-gradient 绘制环形图，展示正向、中性和负向评论比例，待复核评论另列。价格与积分、生成效果等评价维度由关键词规则辅助归类。')
    p('交互方面，用户切换品牌、周期和分析范围后，页面重新请求相应数据并更新图表；点击话题或“查看原声”可查看关联文本。JSON 导出使用 Blob 生成下载文件，历史快照保留生成时的结果。本地行动项状态使用 localStorage 保存，采集与标注管理入口连接独立工作台。')

    p('三 BERTopic 核心算法实现','h',True)
    p('热点发现部分采用 BERTopic，具体由固定 MiniLM 语义编码器、UMAP 降维、HDBSCAN 聚类和 c-TF-IDF 关键词提取组成。输入为品牌相关笔记的标题、正文和评论，输出为话题编号、关键词、文本数量及其关联证据。')
    fig(ASSETS/'dev-bertopic.png','图3 VS Code 中的 BERTopic 源码与模型复核终端')
    p('实现首先清洗文本并去重，过滤过短内容、纯表情和订阅提醒等低信息文本。固定编码器 paraphrase-multilingual-MiniLM-L12-v2 将文本转换为 384 维归一化向量；UMAP 保留近邻关系并降至 5 维；HDBSCAN 根据密度识别文本簇，将难归类的内容标为噪声。')
    p('随后使用 jieba 对同簇文本分词，c-TF-IDF 根据词语在该簇中的频率和跨簇区分能力提取关键词，形成可解释的话题。本次运行采用 n_neighbors=15、min_dist=0、min_cluster_size=30 和 min_samples=3，话题数量由模型拟合结果决定。')
    p('代码位于 collector/weekly/topics.py。训练完成后保存完整降维、聚类和话题表示管线，加载时重新挂接固定编码器。系统用保存的向量执行 transform，验证模型可加载并继续预测。截图中的终端输出来自实际离线复核。')
    p('该实现能够自动归纳相似讨论，为运营人员发现创作需求、会员积分和使用体验等关注点提供线索。泛互动讨论也可能形成大簇，因此用户仍需结合原文判断话题的营销价值。')

    p('四 LinearSVC 情感分类实现','h',True)
    p('评论情感分类采用线性支持向量机的具体实现 LinearSVC，识别正向、中性和负向三类。系统将字符 TF-IDF 与固定 MiniLM 语义向量拼接作为输入，通过线性分类边界区分不同情绪表达，并使用 balanced 类别权重缓解样本数量不均衡。')
    fig(ASSETS/'dev-svm.png','图4 VS Code 中的情感特征构造与固定测试集复现结果')
    p('实现使用 scikit-learn Pipeline 串联特征构造和分类器，GridSearchCV 在训练内部进行三折分组交叉验证，以宏平均 F1 选择参数。本次选择字符 2 至 4 gram、C=1.0，固定语义向量权重为 0.5，编码器不参与微调。')
    p('样本按笔记分组隔离，固定测试评论所属整篇笔记不进入评估模型训练，避免同一讨论串的信息泄漏。评估分类器单独保存；评估完成后，生产分类器再使用全部有效标签拟合。两种模型承担不同用途，页面显示的测试指标来自保留测试集。')
    p('预测时比较各类别的 decision_function 分数。最高与次高分数差小于 0.2 的评论进入待复核状态，该分差用于标识难分样本，不作为概率。预测结果按品牌与时间范围汇总为情绪分布，并与原文证据关联。')
    p('相关代码位于 collector/weekly/sentiment.py 和 semantic.py。图4终端显示实际重载评估模型后得到的分类指标及混淆矩阵，说明分类流程已经运行并可复核。')

    p('五 实现验证与阶段结果','h',True)
    fig(ASSETS/'model-dashboard.png','图5 系统中的模型验证结果与混淆矩阵')
    p('模型验证分为文件加载、预测复现和页面展示三个环节。离线复核脚本检查已保存模型的 SHA-256，重算固定测试集及混淆矩阵，并加载 BERTopic 对已有向量执行预测。2026 年 10 月 26 日的记录表明，两种模型的加载和复现检查均通过。')
    p('BERTopic 对 1,737 条品牌相关输入进行处理，清洗与去重后保留 1,058 条，形成 6 个话题并识别 99 条噪声。系统已实现话题归纳和关键词呈现；当前没有人工话题真值集，话题数量仅表示本次聚类规模。')
    p('情感模型使用 253 条有效标签，其中评估训练 205 条、固定测试 29 条，另有 19 条来自保留笔记。固定测试准确率为 89.66%，宏平均 F1 为 0.6050；两条负向测试样本均预测为中性，负向召回率为 0。测试集全部来自辅助标注，结果用于原型验证，风险候选需人工复核。')
    p('可视化采用真实接口数据，品牌筛选、原文查看、JSON 导出和快照功能已接入。此前 23 项周报离线测试及 JavaScript 语法检查通过，页面交互留有浏览器验证记录。新增数据会使旧分析快照过时，页面通过数据版本与更新时间提示结果新鲜度。')
    p('本阶段完成了主要数据可视化和两种核心算法的落地。后续重点是补充独立人工负向标签、减少泛互动噪声，并在采集覆盖提高后重新分析；当前结果只反映已采样本。')

    update=doc.settings.element.find(qn('w:updateFields'))
    if update is None:update=OxmlElement('w:updateFields');doc.settings.element.append(update)
    update.set(qn('w:val'),'true')
    doc.core_properties.title='小红书品牌营销周报系统部分实践与开发实现'
    doc.core_properties.author='李昊阅'
    stream=BytesIO();doc.save(stream)
    with ZipFile(REFERENCE) as z:original={n:z.read(n) for n in z.namelist()}
    with ZipFile(BytesIO(stream.getvalue())) as z:generated={n:z.read(n) for n in z.namelist()}
    # Preserve existing screenshot parts as well as template styles and page furniture.
    old_rels=etree.fromstring(original['word/_rels/document.xml.rels'])
    new_rels=etree.fromstring(generated['word/_rels/document.xml.rels'])
    existing={n.get('Id') for n in old_rels}
    for relation in new_rels:
        if relation.get('Id') not in existing:old_rels.append(deepcopy(relation))
    generated['word/_rels/document.xml.rels']=etree.tostring(old_rels,encoding='UTF-8',xml_declaration=True,standalone=True)
    allowed={'word/document.xml','word/_rels/document.xml.rels','word/settings.xml','docProps/core.xml'}
    final=dict(original)
    for name,data in generated.items():
        if name in allowed or name not in original:final[name]=data
    with ZipFile(OUTPUT,'w',ZIP_DEFLATED) as z:
        for name,data in final.items():z.writestr(name,data)
    assert hashlib.sha256(REFERENCE.read_bytes()).hexdigest()==source_hash
    assert all(final[n]==data for n,data in original.items() if n not in allowed)
    (TMP/'verification.json').write_text(json.dumps({'output':str(OUTPUT),'reference_sha256':source_hash,
        'changed_parts':[n for n in original if original[n]!=final[n]],'figures':5},ensure_ascii=False,indent=2),encoding='utf-8')
    print(OUTPUT)


if __name__=='__main__':build()
