# 第一阶段结构与 Metalks 对接

## 数据与引用

Corpus → CorpusResource → Resource → ResourceVersion → Fragment。

- Resource 沿用 `resource_id / owner_user_id / resource_kind / system_tags / source_type / source_ref_id / content_hash / visibility` 等约定；版本与片段是本项目独立表，没有直接导入 Metalks ORM。
- `visibility` 表示 active / archived，不代表公开权限。
- 正文快照不可变。片段 ID 包含版本身份；偏移指向该版本正文，Unicode code point，左闭右开。
- 同名文件更新内容会作为新的资源导入，当前没有编辑、分支或原地版本更新 UI。用户可以归档旧资源。本阶段支持不可变版本基础，不宣称已实现 Metalks 完整分支系统。
- 相同语料库内，同名、同正文、同出处重复上传复用资源与任务。出处变化也会产生不同身份。
- 归档立即阻断检索和上下文访问；旧向量可保留以支持恢复。归档内置卷不会在重启时自动恢复。

## 向量索引与返回规则

每节经文保存一个 Fragment，另为句中引号包含的短对话建立索引项。索引项仅保存 Fragment ID、片段内起止位置和 generation；展示文本从 SQLite 中的原文切片还原。整节和短句共享出处。节内摘录会明确标注“节选”，可展开整节和相邻节。

现阶段索引全文片段与短对话摘录；相邻上下文用于展示，尚未另外向量化相邻经文窗口。繁简归一化、关键词混合召回和重排序也未实现。BGE 是可用基线，不保证语义相似的句子一定适合直接用于每一种对话。

检索前确定当前语料库中可访问资源的有效 generation，Qdrant 在该集合内召回。多取候选并按 Fragment 去重；若重复索引项挤占候选，继续扩大召回直到满足 top_k 或候选耗尽。没有相似度阈值：语料充足时返回 top_k，不足时全部返回。分数只用于内部排序，不出现在 API 或界面。

索引任务持久化在 SQLite。当前一个应用进程启动一个后台线程，串行处理；批量编码、幂等写入 Qdrant。用户上传任务优先于剩余内置语料。重启时 processing 任务恢复 pending。同一 generation 内点 ID 固定，重放不会产生重复点。新 generation 完整成功后在事务中切换 active_generation；失败仍使用旧索引。旧批次清理失败不会使其重新可见。

Qdrant 本地模式只能单进程持有。切换独立服务时先重建索引，独立服务并发能力尚需专门验证。模型或切分算法改变必须使用新的 collection / revision 并重建，不能混用不同向量空间。

## 与 Metalks 的实际差异

参考了以下现有代码：

- `D:/Metalks/backend_constellation/resource_pool/models.py`
- `D:/Metalks/backend_constellation/resource_pool/repository.py`
- `D:/Metalks/backend/db/models/core.py`
- `D:/Metalks/backend/utils/text_context.py`

Metalks 当前 MySQL Resource 仓储的 search_semantic 尚未实现，现有语义召回主要面向记忆陈述。此处可以成为“原始语料向量检索”的实验基础，但还没有完成直接数据互通。

后续适配器应完成：

1. 将当前用户映射到真实 owner_user_id，从 Metalks 资源仓储获取固定版本快照。
2. 将资源权限转换为检索前的过滤条件，失权后同时阻止引用与上下文读取。
3. 将 Metalks 版本 ID 和内容哈希带入索引任务，资源变化时构建新 generation。
4. 将 Citation 和本项目片段 ID 作为扩展映射保留，不直接复用可能跨版本覆盖的片段编号。

## 后续表达模型

第一阶段不调用生成式模型，不声称引用文字是改写结果。未来独立定义 StyleProfile 与 rewrite 请求：输入原表达、目标语料库固定版本、语义约束、长度和文风强度；输出改写文本、参考片段、直接引用范围、模型实验版本。内部可以替换成新的训练架构。

训练数据与检索数据分离；用户选择某条引文仅代表检索偏好，不能直接当作长文本改写的真值。效果评估需要独立的日常表达查询集、相关性标注以及语义保持反例。
