# 上游来源与移植说明

## 原项目

- 项目：[nonebot-plugin-majsoul](https://github.com/bot-ssttkkl/nonebot-plugin-majsoul)
- Python 模块名：`nonebot_plugin_majsoul`
- 原作者：**ssttkkl** 及上游贡献者。
- 上游许可证：GNU Affero General Public License v3，完整文本保存在根目录 LICENSE 和 licenses/LICENSE。
- 本地迁移环境中安装的上游发行版标识为 **0.2.10**；该副本包含本地修改，无法据此断言所有代码等同于上游某个提交。

## 继承与修改

保留并适配上游的数据模型、房间与时间解析、统计映射、PT 绘图和镜像探测等业务代码。保留原作者和贡献者的相应权利。

AstrBot 入口、配置表单、绑定存储、事件输出与生命周期经过移植。相较于原插件的功能与行为差异集中列于 [CHANGELOG.md](CHANGELOG.md)，包括可配置 AI 锐评、PT 图上限、密钥开关、授权/限流处理、文字对局输出及牌谱下载功能的移除。

移植维护者：**ChoToHi**。此版本整理及修改年份：2026。各文件中的原有版权声明予以保留。AI 辅助参与了移植和文档整理。

## 字体及服务

`paifuya/NotoSansCJK-Regular.otf` 未作修改。字体内嵌名称为 Noto Sans CJK Regular，版本 1.000，版权为 © 2014 Adobe Systems Incorporated，其嵌入许可明确指向 Apache License 2.0。本仓库保留该许可文本及 NOTICE，不套用其他版本字体的许可。

查询使用牌谱屋接口，参考 [amae-koromo](https://github.com/SAPikachu/amae-koromo)。运行依赖的 AstrBot 等项目各自保留其许可证；本仓库不包含这些依赖的源码副本。
