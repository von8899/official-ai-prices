# Official AI price snapshots

个人维护的官方 API 单价快照；数据来源是 Anthropic、OpenAI、Google 的公开官网。所有金额为 USD / 1M tokens。

## 范围
- Claude / OpenAI 55 款已核验模型。
- Gemini 12 款聊天/推理模型的付费 Standard 文本 Token 价格。
- 缓存读取、可计量的缓存写入及公开上下文档位。
- 图片生成、音频、视频、工具调用、缓存驻留费不混入普通文本 Token 记账。
- 这里只提供价格，不代表订阅账号能调用全部模型。

## 更新
GitHub Actions 每天 22:17 UTC（北京时间06:17）抓取官网。脚本不使用AI、不调用模型API、不需要厂商账号。
- 小于等于20%的正常价格变更自动发布。
- 已核验、已公布生效日期的促销调整按日期处理。
- 单位/档位/组件变化、意外大幅调价、缺失模型保留旧快照，写入待审核文件。
- 新模型需要审核后加入 registry.json；不会自动开通账号权限。
- 日期条件按UTC日期计算；每日任务不是实时价格保证。
- 网络/解析失败保留原价格，通过 manifest.json 显示状态，不回填0。

## 低流量消费
每天读取 data/manifest.json（小于2KB）。sha256未变就结束；变化才下载 catalog.<sha256>.json，并验证SHA-256和结构。
价格快照为不可变文件。查询状态与价格版本分开，因此成功检查但没改价时不必下载全部价格或写数据库。

公开数据入口：[manifest.json](data/manifest.json)。待审核：[pending.json](data/pending.json)。

## 隐私与部署
仓库不含任何服务器地址、后台凭据、API key、用户信息或调用记录。消费端凭据只应在消费端本地保存。
消费者应只处理数字价格，不执行下载内容；校验成功并备份后应用。失败保留旧价，历史记录不回算。
公开快照不是订阅账单或剩余额度；某些反代 usage 缺少细分收费项，只能统计明确返回的用量。

## 开发
使用Python标准库：python3 -m unittest discover -s tests -v；python3 sync_prices.py。
审核 pending.json 的具体变更后，可将candidate_hash加入policy.json的approved_catalog_hashes，再手动运行workflow。
不要仅为消除报错而批准未知单位、丢失模型或未知上下文阈值。
