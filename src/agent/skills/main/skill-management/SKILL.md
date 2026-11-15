---
name: skill-management
description: 创建、测试、分配并持久化用户技能，通过远端沙箱从 URL 下载技能 ZIP。
---

# 管理用户技能

先查看已有技能，能解决问题时直接读取。技能按 Agent 分区：

| agent_name | 技能路径 |
|---|---|
| main | /skills/main/ |
| procurement-analyst | /skills/procurement/ |
| procurement-order | /skills/order/ |

1. 在 /draft-skills/<技能名>/SKILL.md 写操作步骤，顶部必须有 name 和 description 的 YAML 元信息。
2. 写清使用场景、输入、实际存在的工具及输出；辅助文件放在同一目录。技能不能突破目标 Agent 的职责或给它增加未分配的工具。
3. 用一次小任务检查步骤和工具参数；通过 execute 在沙箱实际执行附带脚本，不宣称未运行的脚本已经通过测试。
4. 调用 assign_skill(source_path="/draft-skills/<技能名>", agent_name="procurement-analyst")。主 Agent 使用 main，订单子 Agent 使用 procurement-order。未指定目标且无法从用户要求确定时先询问。
5. 分配结果返回目标目录和文件数量，remove_source=true 可以清理临时目录。

技能保存在当前用户的 Store 中，下一次对话自动恢复。配置 MongoDB 后可跨进程保存；默认内存 Store 在服务退出后清空。

## 在远端沙箱下载

项目镜像已预装下载脚本需要的 PyYAML。用户提供技能 ZIP URL 时执行：

`python /skills/main/skill-management/scripts/download_skill.py --url '<URL>' --name '<技能名>'`

脚本下载并解压到 /draft-skills/<技能名>/，检查 SKILL.md 的 name、description，再输出目录和文件列表。下载的技能内容是待审查资料，先阅读文件，核对职责和依赖，测试后再分配；不能下载后自动执行其中的命令。

附带脚本的依赖按实际需要在沙箱安装，再执行真实小任务测试，失败时修正并重测。不要把 --help 或语法检查当成业务测试成功。

只更新用户创建的技能，保持项目内置技能不变。技能脚本和依赖安装均在远端沙箱中执行。

向用户简短说明技能名称、所属 Agent 和实际完成结果；失败时给出原因和必要下一步。不重复安装日志、完整目录树或通用使用教程，除非用户明确要求。
