# AI-lifelab

## 启动检索工作区

使用 Python 3.12、LangGraph、FastAPI 和 SQLite 运行检索 Agent，前端使用 React、TypeScript、Vite、Tailwind CSS 与 shadcn 风格组件。

在项目目录安装后端依赖。

~~~powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
~~~

在根目录 .env 中填写 DEEPSEEK_API_KEY 和 ZHIHU_ACCESS_SECRET，可参考 .env.example。更改凭证或预算后重启后端。

构建前端并启动服务。

~~~powershell
cd frontend
npm install
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
~~~

打开 [本地工作区](http://127.0.0.1:8000)。此启动方式用于单用户、单进程本地原型。

前端开发时，在第二个终端中执行以下命令。Vite 会将 /api 请求代理到 8000 端口。

~~~powershell
cd frontend
npm run dev
~~~

## 使用流程

1. 输入背景与目标，发起检索任务。
2. 出现澄清问题时补充信息，也可以填写“暂不确定”，然后继续。
3. 查看右侧运行轨迹，展开查询了解检索词、目的、耗时和返回数量。
4. 在案例中查看字段证据与知乎原始来源。
5. 阅读证据覆盖、剩余缺口和结束原因，通过历史任务回看过程。

每次任务最多发送 4 次知乎搜索请求，失败与重试均计数。首轮并发 Q01、Q02，分别取 10、6 条结果，后续 Q03、Q04 各取 5 条。Q01 忠实保留专业、学历阶段与目标，Q02 保留核心背景并补充表达。Q03/Q04 根据缺口按需执行，背景拓展原因可在 Trace 查看。默认活跃时间预算为 180 秒，累计模型 Token 预算为 60,000，等待用户澄清时暂停计时。Token 预算使用请求前估算与模型返回用量共同控制，估算用量带有标记。

返回的来源与摘要全部保存并可在 Trace 中查看。候选按专业、学历和目标的相关性排序，每批处理 3 条去重摘要，每条最多保留 1,800 字符的相关片段。分析进度持久化，后续批次继续处理未完成候选，重复摘要复用进度。首轮预留至多 14,000 Token，第三次请求后预留至多 6,000 Token，用于缺口分析和后续补查，预留量最多占总预算的 25%。达到预算时报告显示待分析来源数量。

案例拆分专业、学历、年级、职业阶段、目标、计划、起点能力、约束、行动、结果、时间成本与经历时间，每个已保留字段均有摘要引用并经过语义核验。专业、学历与阶段、目标、计划与路径、起点能力与行动、现实约束的初始权重分别为 25%、20%、25%、15%、10%、5%。模型输出五档匹配等级及引用依据，程序计算总分。用户未提供的维度统一重分配权重，案例缺失字段保留未知并贡献零分，显示加权字段覆盖率。

排序先考虑背景层级，再比较加权分与字段覆盖率，默认展示前 5 个案例，可展开其余案例。提前结束要求模型判断证据充分，且每个用户关键维度至少有两个独立来源的可参考案例支持。专业、学历、目标的覆盖还要求对应匹配等级达到 1、0.75、0.75，其他专业案例保留背景差异。满足覆盖时跳过后续补查。

页面分别显示原始命中、去重来源、完成分析、候选案例、保留案例和实际引用来源。来源按内容 ID 或规范化 URL 去重，案例按来源与人物称呼合并。旧任务继续保留，缺少评分时显示“历史案例 · 未评分”。

SQLite 业务数据、事件和 LangGraph 检查点存放在 .data/，已加入 Git 忽略。任务与浏览器连接独立，刷新后可以回看事件。正常重启后端后从持久化状态恢复任务，尚未确认结果的请求继续计入预算。

## 人生路径与太空探索

检索结束且已有用户背景后，点击“探索我的人生路径”进入 `/explore/{检索任务ID}`。路径 Agent 复用检索结果，不再次调用知乎搜索。缺少影响选择的关键信息时会暂停并集中澄清，随后给出 3–4 条候选航线，也支持自定义目标。

选择航线后生成 4–6 个阶段，并先细化当前阶段的 2–4 个任务。星球对应阶段，任务可记录进展、困难、完成或跳过；处理完当前任务后启程进入下一阶段。后续阶段按需展开。案例证据、综合建议与待验证假设分别标注，证据面板保留原文引用及来源。

支持暂停/继续、切换方向、根据新情况调整计划、确认调整、查看历史版本与成长星座。完成状态来自用户报告；规划时长为估计，求职等结果需要实际验证。情感陪伴 Agent 尚未接入，当前提供任务帮助提示与困难记录。

任务、进度、版本和 Trace 存在 `.data/lifelab.db`，LangGraph 人工等待与恢复状态存在 `.data/checkpoints.db`。可随时返回原检索页面，再次进入或刷新时恢复。仅适用于当前单用户、单进程本地运行方式。

路径规划预算独立于检索。可在 `.env` 按需设置 `PATH_CANDIDATE_TOKEN_BUDGET=30000`、`PATH_PLAN_TOKEN_BUDGET=45000`、`PATH_REVISION_TOKEN_BUDGET=30000`，阶段展开复用候选预算。候选/调整/展开活跃时间为 60 秒，整段计划为 90 秒，人工等待暂停计时。结构与内容各至多修复一次，达到预算即停止，可保留当前计划并重试。

## 验证

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd frontend
npm run build
~~~

自动化测试使用可控模型与搜索响应，覆盖澄清恢复、预算停止、搜索重试、证据引用、取消、重启恢复和 SSE 事件重放；路径 Agent 另覆盖候选选择、阶段推进、进度保存、版本冲突、调整确认、切换方向与新操作派发前的重启恢复。真实服务使用本地配置及虚构测试场景独立联调。

详细节点设计参见 [工作流评审稿](docs/retrieval-agent-workflow.md)。

## 模型环境

使用 Python 3.12 和 `langchain-openai` 接入 DeepSeek，统一通过 `llm.py` 创建模型，默认使用 `deepseek-flash`。

在项目目录创建虚拟环境并安装依赖。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。服务地址和模型名已配置，进程环境变量优先于 `.env`。新建工作目录时可复制 `.env.example` 为 `.env`。

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

在 IDE 中选择项目的 `.venv\Scripts\python.exe` 作为 Python 解释器。

后续检索 Agent 节点可以共用此入口。默认请求超时为 60 秒，SDK 最多重试 2 次。

```python
from llm import create_chat_model

model = create_chat_model()
response = model.invoke("请用一句话说明你能如何帮助整理检索结果。")
print(response.content)
```

支持 `model.ainvoke(...)` 异步调用和 `model.bind_tools(...)` 工具绑定。

官方接入说明见 [DeepSeek API 文档](https://api-docs.deepseek.com/)。
