# 本地验收记录

验收日期为 2026-11-11，环境为 macOS ARM64、DeepSeek Harness 0.2.2-rc.1、Python 3.13.9 和 PyMuPDF 1.25.2。

## 结果

| 检查 | 实际结果 |
| --- | --- |
| skill 元数据 | 通过 skill 校验，名称符合 dsh 规则 |
| 真实 dsh 注册服务 | 从默认用户 skill 目录发现并完整加载，用户和模型调用均启用 |
| 本地回归测试 | 15 项全部通过 |
| GitHub 安装验证 | 从公开仓库重新克隆，注册加载和 15 项测试通过 |
| 真实 dsh 会话 | 通过 `/pdf-translate` 注入技能，完成提取、翻译、写回和复核，进程退出码 0，终态 `completed` |
| 输出 PDF | 生成 1 页简体中文译文，标题和正文均已翻译，文字可提取 |
| 内容保护 | 表格、图片、标题说明、代码、参考文献的文字及 2 倍分辨率像素一致，链接保留 |
| 版式检查 | 页尺寸、源正文字体、标题 17 pt、正文 12 pt、基线和行距保留 |
| 原文完整性 | 输入 PDF 的 SHA-256 保持一致 |

回归测试还覆盖中译英、横排日文译简中、扫描页保留、原文哈希与块决定校验、续作、已有输出和并发输出冲突。测试使用代码生成的文档。

## 模型测试配置

本机默认的 DeepSeek API-key 路由和 `deepseek-account/deepseek-v4-pro` 路由均返回 HTTP 404。端到端验收通过一次性 headless 配置使用本机已配置的 `gpt-6-astra` 路由，复用 dsh 的模型适配器及凭据服务。

已验证的是当前会话模型驱动的完整 skill 工作流。DeepSeek 默认模型的实际翻译能力在本次环境中未完成验证。辅助 Python 程序负责 PDF 操作，译稿由实际 dsh 会话生成。

该会话还按技能规则检查并修复了辅助排版器产生的基线差异，再次进行整页视觉与保护区域核对。最终 PDF 另经独立程序复核。

## 复测

安装依赖后运行

```sh
.venv/bin/python -m unittest discover -s tests -v
```

真实 dsh 注册服务及样例生成命令见 [README.md](README.md)。完整模型验收可在桌面 dsh 中提供生成的 PDF 并输入 `/pdf-translate`。自动化验收使用本机 dsh 的 headless 入口，其登录与配置方式遵循官方说明。[dsh headless 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/headless/README.zh.md)

## 验收范围

真实模型验收样例为一页生成文档，覆盖明确分离的正文和保护区域。多栏论文、混合块、复杂公式及长文档仍需依照技能规则逐页审校。Windows 和 Linux 尚未在本次验收中运行。
