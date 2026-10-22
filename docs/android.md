# Android 离线实现与验证

## 实现

Android Activity 托管系统 WebView，以固定 HTTPS 虚拟来源提供 APK 内的静态资源。页面、Worker、圣经正文、向量索引和 BGE 模型全部随包分发；没有 INTERNET 权限，不会访问远程后端。外部页面不能导航进有原生桥接的 WebView。用户通过系统文档选择器主动选择文件，不申请全盘存储权限。

原生桥接只有编码、复制和关闭功能。ONNX Runtime Android 1.23.2 在独立执行器上运行，使用与 FastEmbed 对应的大小写敏感 BERT WordPiece 分词、512 token 截断、CLS pooling、L2 归一化。`android/check_embedding.py` 在 JVM 上对照 Python 输出，验证的是同一 Java 编码实现；它不是 Android JNI 的设备测试。

Worker 负责切分、IndexedDB 持久化、进度和检索。预置向量由 `android/export_assets.py` 从经过验证的干净圣经库导出，float32 512 维，34,627 个完整段落/原文短句向量，对应 31,100 节原文。手机端以精确点积排序并按 fragment_id 去重；默认 top 50，不显示分数。这里使用移动端内存索引，不运行 Qdrant；服务器与 Windows 的 Qdrant 架构保持原样。

自定义资源包含 resource_id、resource_kind、owner_user_id、source_type、source_ref_id、system_tags、version_id、content_hash、fragment_id、citation 等字段。字符位置按 Unicode code point 的半开区间记录。两端尚未实现导出同步协议，不能直接将手机 IndexedDB 当成 Metalks 数据库导入；后续需增加适配与资源身份映射。

导入事务先保存正文与 pending 任务，再异步编码。索引替换在整份资源编码完成后执行；旧索引在重建期间可用。应用被终止时，中断任务下次启动重新处理。删除语料库和资源过滤检索可见性，语料库可恢复。用户上传内容始终按文本展示。

## 构建

`setup_tools.py` 使用 Microsoft OpenJDK 17、Google Android Build Tools 35 和 API 35 平台、Maven Central 上的 ONNX Runtime AAR。SDK/JDK 校验官方发布摘要。构建不依赖 Android Studio 或全局 Java。`build.py` 顺序执行 javac、D8、aapt2、zipalign 与 apksigner；ARM64 专用，minSdk 26、targetSdk 35。仅将应用源代码、静态页面、公共圣经数据、模型和许可证装进 APK。

签名材料不进入发布目录；`build/android-signing` 含后续更新必须使用的私钥与口令，应私下备份。构建不会重新生成已有密钥。正式发布商店前仍需补充设备验收、版本升级策略和商店资料。

## 本次验证

- 10 项 Python 回归测试通过，含旧集合名到新集合别名的迁移，确认已有检索数据仍可使用。
- Java 编码器 7 组对照通过，包含中文、英文、Unicode 扩展字符、特殊 token、长词和截断；最大向量逐维误差 2.91e-7。
- Node 离线业务验证通过：原文位置、预览、50 条圣经结果、出处、上下文、分页、自定义导入与重复检测、索引、删除、恢复、资源移除。
- APK 的实际前端构建在 390 像素宽浏览器中通过 Worker 检索和文件选择导入；页面重新加载后，自定义语料仍在 IndexedDB 中，检索返回两条原文。这里的原生桥接被固定的真实模型测试向量替代，未声称测过 Android WebView。
- 常规本地预览在 320 / 390 像素宽度无横向溢出，前端单独 npm 构建通过并保留 frontend/dist。
- APK v2 / v3 签名和 ZIP 对齐验证通过。最终摘要存 release/SHA256SUMS.txt。
- 未连接 Android 真机或模拟器；安装启动、原生 JNI、系统文件选择器、中文字体回退、不同 Android 版本和实际耗时/内存仍需设备验收。

浏览器 QA 使用 `local-preview/android-preview.py`，仅绑定 127.0.0.1:5174，并仅支持固定测试语句。它不属于 APK，也不应作为日常应用入口。
