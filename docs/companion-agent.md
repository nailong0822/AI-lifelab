# 随航伙伴：情感陪伴 Agent

## 使用

先生成一条人生路径，然后在太空探索顶部点击“随航伙伴”。任务中的“记录 / 求助”自动关联具体阶段与任务；可取消关联自由聊天。支持“自在聊聊”“先听我说”“一起想办法”三种偏好。

对话、操作结果、记忆及事件保存到现有 `.data/lifelab.db`，LangGraph 使用同一个 checkpoints.db，但每轮会话有独立线程 `companion:{turn_id}`。刷新与正常重启后可继续；同一航程共用一份会话和记忆。此版本仍是单用户、单进程本地原型。

## 工作流

`load → plan_web → [search_web] → respond → validate → publish → automatic → wait(interrupt) → apply`

- load 读取当前真实计划、任务、前置依赖、进度、关联任务及有上限的近期对话与原话摘要。
- plan_web 通过 DeepSeek tool calling 按问题决定是否调用通用 web_search；未配置、关闭或安全分流时跳过。搜索、原文读取、缺口补搜和引用校验详见 [Web Search 说明](web-search.md)。
- respond 使用 DeepSeek Flash 生成结构化回应、最多一个小行动、可选引用及操作提案。通常一次调用，仅允许一次结构修复。
- validate 校验原话引用、真实任务ID、完成语义及用户禁止操作的要求。假设、否定、他人成果不自动写成用户完成。
- publish 幂等保存助手消息和操作。明确、唯一关联且满足条件的完成反馈可自动更新，显示用户自述依据并提供撤销。
- 其他操作以卡片等待选择。LangGraph interrupt 持久化；用户可以先聊下一条消息，再处理旧建议。执行时核对最新版本与进度。

检索、路径和陪伴使用同一模型适配入口 `DeepSeekModel` / `llm.py`。此版本以真实 SSE 节点事件和完整消息返回，不模拟逐字生成。Trace 不展示模型内部思考。

## 操作边界

任务进度复用 PathStore.update_progress，计划版本、进度修订、任务依赖和暂停状态都必须通过；路径更新与伙伴操作结果共用一个 SQLite 事务。重复提交消息或决定不重复执行操作。撤销只允许未被后续进度或阶段变更覆盖的操作。

跨阶段成果先保留为 achievement 记录，不自动补齐前置任务。计划调整交给现有 PathService.revise，使用操作ID防重复生成，并沿用路径 Agent 的“生成草案→用户审阅→保存新版本”。伙伴建议不冒充用户完成证据，只有真实用户原话进入已完成判断。

伙伴不会执行任意电脑命令或声称已经代替用户运行代码。无来源时提供一般建议，引用展示保存的原文和链接。危机表达切换安全支持，停止任务和记忆操作；不提供心理诊断、结果保证或排他依赖话术。

## 记忆与预算

只保存用户确认的偏好、已有能力和现实约束，保留来源消息。修改或删除记忆会清除相关摘要，原来源轮次不再进入模型近期上下文；聊天记录仍可回看。当前 SQLite 为本地普通数据库，不宣称加密保存。

预算独立于路径和检索，普通每轮累计 80,000 Token、60秒活跃时间。普通输出最多1800 Token，“一起想办法”最多2500 Token；实际联网的消息默认提升至至少100,000 Token、90秒，最终答复最多3200 Token。工具决策、缺口分析和答复累计计入本轮用量。模型失败或中断时保守保留已预留用量；重试不重置累计预算。人工等待不持续消耗模型预算。达到本轮预算可缩短内容后发送新消息。

可选 `.env` 配置：

```dotenv
COMPANION_TOKEN_BUDGET=80000
COMPANION_TIME_BUDGET=60
```

服务端配置更改后重启后端。前端修改后运行 `npm run build`，继续通过现有后端提供静态页面。

## HTTP 与 SSE

- `POST /api/paths/{path_id}/companion/sessions`：幂等获取航程会话。
- `GET/POST /api/companion/sessions/{session_id}/messages`：回看与发送，支持 before 游标获取更早消息。
- `POST /api/companion/turns/{turn_id}/retry`：重试失败回应。
- `POST /api/companion/actions/{action_id}/respond`：采用或拒绝建议。
- `POST /api/companion/actions/{action_id}/undo`：撤销安全范围内的进度更新。
- `GET /api/paths/{path_id}/companion/memories`，`PATCH/DELETE /api/companion/memories/{memory_id}`：管理记忆。
- `GET /api/companion/sessions/{session_id}/events`：SSE 事件，支持 after 与 Last-Event-ID 重放。

自动化测试使用虚构数据和本地模型桩，覆盖对话恢复、人工确认恢复、幂等、预算、语义拦截、事务更新、版本冲突、撤销、记忆纠正、危机分流及与路径 Agent 的协作。真实模型联调也只使用隔离目录中的虚构场景。
