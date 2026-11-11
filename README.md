# dsh PDF 翻译

适用于 DeepSeek Harness 的原生 skill。使用当前 dsh 会话所选模型和思考设置翻译电子 PDF，本地 Python 完成提取、排版及检查，交付单语 `译文.pdf`。

支持英译简中、中译英、横排日文译简中。翻译前建立全文上下文和术语表，原样保留表格、图片及其说明、参考文献、代码与公式。

## dsh 适配依据

dsh 的文件系统 skill 支持 `SKILL.md`、辅助脚本和参考资料，提供用户目录自动发现和 `/name` 调用。这套会话翻译流程使用上述原生能力。dsh 的工具、UI 和生命周期扩展则采用 Cordis 插件接口。

技能名称遵循 dsh 的小写字母、数字和连字符规范，使用 `pdf-translate`。本机已验证的 dsh 版本为 `0.2.2-rc.1`。

- [官方 skill 文件格式与安装位置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.zh.md)
- [官方 skill 调用方式](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/tool-skill/README.zh.md)
- [官方插件扩展接口](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cookbook/extension-cookbook.zh.md)

## 安装

需要已安装的 DeepSeek Harness、Git 和 Python 3.10–3.13。以下命令将技能安装到 dsh 默认用户目录。设置了 `DSH_HOME` 时使用相应目录。

```sh
git clone https://github.com/chaohuawang-phd/dsh-pdf-translate.git "${DSH_HOME:-$HOME/.dsh}/skills/pdf-translate"
cd "${DSH_HOME:-$HOME/.dsh}/skills/pdf-translate"
python3 scripts/setup.py
```

若 `python3` 版本过旧，使用本机的 `python3.13` 等受支持解释器执行安装。依赖固定为 `PyMuPDF==1.25.2`，安装在技能自身的 `.venv`。Windows 使用对应用户目录和 `py -3.13 scripts/setup.py`，运行解释器位于 `.venv/Scripts/python.exe`。

dsh 会自动发现技能。打开对话，附上 PDF 或提供可读取的文件路径，然后输入

```text
/pdf-translate 将这份 PDF 翻译成简体中文，保存到我指定的输出目录。
```

英文译入方向可明确写“翻译成英文”。完整操作指引见 [SKILL.md](SKILL.md)。

## 运行方式

当前会话模型阅读全文、维护术语和保护区域记录、生成按块关联的译稿。辅助程序提供提取和写回两个阶段，通过原文哈希及块 ID 核验译稿。

```sh
.venv/bin/python scripts/paper_translation_workflow.py translate \
  --input /path/to/source.pdf --output /path/to/delivery --target-language zh
```

第一阶段返回临时清单、译稿路径和 `render_argv`。模型完成译稿后，使用返回参数和覆盖全部译文字形的 `--font` 文件写回。输出目录中出现已有 `译文.pdf` 时，另选新目录。

PDF 提取和排版在本地执行。原文与译文会进入当前 dsh 会话，其模型请求遵循 dsh 已配置的服务和账号。

## 测试

```sh
.venv/bin/python -m unittest discover -s tests -v
```

测试使用生成的样例，覆盖三种翻译方向、保护区域、源文与译稿校验、扫描页和输出冲突。

macOS 上可用已安装 dsh 的真实技能注册服务验证发现与加载。运行前先将技能安装到用户目录。

```sh
ELECTRON_RUN_AS_NODE=1 '/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness' \
  --expose-internals tests/check_dsh.cjs pdf-translate /tmp
```

真实模型端到端测试的样例由以下命令生成，再在 dsh 中用 `/pdf-translate` 翻译该 PDF。

```sh
.venv/bin/python tests/create_smoke_pdf.py --output .test-output/source.pdf
```

## 版式范围

辅助程序支持整块替换。正文与公式、代码或图表共处一个块时，模型需要按保护边界进行局部排版。复杂粗斜体、行距、缩进和译文内链接同样需要逐页复核。现有排版器允许缩放至原字号的 75%，需依据成品检查同类文本字号一致性。

扫描页和文字转曲页保留原貌。该版本保留原 skill 的人工审校步骤，具体规则见 [学术翻译规则](references/academic-translation-policy.md)。

## 来源和许可证

基于 Double6 PDF Translation 3.1.0 及其本地会话翻译版本，采用 AGPL-3.0-only。发行包包含当前会话路线及其依赖源码。修改记录见 [MODIFICATIONS.md](MODIFICATIONS.md)，许可证全文见 [LICENSE](LICENSE)。
