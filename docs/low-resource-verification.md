# 低资源运行验证（2026-10-27）

本次以降低后台资源占用为目标，保留原模型和 512 维向量格式。默认每批 8 条、1 个推理线程，关闭 ONNX CPU 内存池；后台闲置检查在无推理活动 60 秒后释放模型，并在 Linux/glibc 上尝试归还空闲堆内存。索引使用按片段序号分页读取，同时限制引语展开后的编码与写入批次，每批暂停 0.1 秒。

## 真实模型对比

环境：Windows、Python 3.13.5，项目现有虚拟环境与本地缓存 `BAAI/bge-small-zh-v1.5`。两个独立进程分别处理同一组 64 条长文本及一个查询，使用离线模式。此测试单独测量模型路径，未加载业务向量库；服务器完整进程还包含语料向量及元数据。Windows 使用工作集统计。

| 指标 | 原配置（64 条 / 4 线程 / 内存池开启） | 新配置（8 条 / 1 线程 / 内存池关闭） |
| --- | ---: | ---: |
| 推理前内存 | 115.9 MiB | 115.8 MiB |
| 推理峰值内存 | 1231.3 MiB | 395.6 MiB |
| 推理后内存 | 1221.7 MiB | 227.6 MiB |
| 闲置处理后内存 | 1221.7 MiB | 135.2 MiB |
| 编码及模型加载总耗时 | 3.69 秒 | 14.05 秒 |

新配置的峰值降低约 68%，推理后占用降低约 81%，闲置处理后占用降低约 89%。闲置测试通过调整最后使用时间触发真实卸载函数，没有实际等待一分钟。64 条文本向量和查询向量与基线的最大绝对差均为 0；卸载后重新加载生成的查询向量最大绝对差也为 0。

复现命令（在项目根目录执行，每条命令启动一个独立进程）：

```powershell
.venv\Scripts\python.exe scripts\benchmark_embedding_memory.py --baseline --output data\test-runs\memory-baseline.json
.venv\Scripts\python.exe scripts\benchmark_embedding_memory.py --output data\test-runs\memory-low-resource.json
```

脚本保存 JSON 内存统计和同名 NPZ 向量，用于逐项对比。原始本次结果位于 `data/test-runs/memory-{baseline,low-resource}-20261027.{json,npz}`。这些本地测试产物不进入代码仓库。

## 回归结果

全部 **22 项测试通过**，覆盖语料检索、隔离、归档恢复、原文偏移、重复上传、重建索引、HTTP 来源校验，以及新增的小批次引语编码、中断任务幂等重放、模型闲置卸载和重新加载、推理锁保护、资源配置校验。

```powershell
.venv\Scripts\python.exe -m pytest -q -o faulthandler_timeout=30 --basetemp=data\test-runs\resource-limits-full-20261027
```

首次在受限 Windows 沙箱运行时，FastAPI 测试客户端的 asyncio 本机 socketpair 卡在连接建立阶段；栈定位后，在沙箱外使用独立测试数据库重跑，通过耗时 8.94 秒。现有 Starlette/httpx 弃用提示保留。

## 部署

服务器更新步骤见 [低资源更新](inner-office-deployment.md#低资源更新)。安装 systemd drop-in 后，应用 CPU 配额为半个核心，并降低 CPU/I/O 权重，保留原有 ExecStart、虚拟环境和数据路径。此轮未连接服务器，Linux 内存回收和 systemd 限额需在更新后按部署文档观察。
