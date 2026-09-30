# 可靠性评测准备交接

已建立新版本 `reliability-v1`，本轮为评测准备，无功能扩展、无真实 API 调用。

| 项目 | 结果 |
|---|---|
| 数据规模 | 39 episode / 45 turn / 13 场景类 |
| Dev | 13 episode / 15 turn |
| Holdout | 26 episode / 30 turn，仅结构校验 |
| Dev 离线契约 | 13/13；脚本替身，不是模型准确率 |
| Holdout Agent 执行 | 0 |
| 真实 API 调用 | 0 |
| 产品核心修改 | 无 |
| 后端完整回归 | 221 passed（含新增 12 项评分器测试） |
| 检查 | 新增 Python 文件 Ruff / 格式通过；更新文档相对链接有效 |

新增数据生成器、逐 turn 评分器、隔离 Dev 运行器、数据库前后证据、幂等重复检查与不可覆盖 manifest。记录配置/Prompt/Tool/源码/数据 hash，配置使用白名单，不保存凭据。修正开发期间的金标准金额与数据库货币单位比较，未更改产品计算方式。

新增评分器回归检查越权被阻止与成功越权的区别、参数错误、缺少结束工具证据、额外工具效率、已有记录被改动、元/分金额和凭据不进入配置。验证结果与完整命令输出见 [checks](verification/reliability-evaluation/checks.json)；完整 Dev 轨迹在 [Dev summary](verification/reliability-evaluation/dev-offline.json) 与同目录 `dev/`。

本轮没有重复前端/E2E，也没有运行历史冻结 Test。README 保留历史 92% 的原始口径，只新增本轮准备材料入口。

## 限制与下一步

该 Holdout 是已知业务契约上的新措辞，不能宣称业务家族隔离、生产流量或盲测泛化。评分器可以验证记录与确定性事实，但不替代人工检查所有真实模型失败。恢复故障依赖独立工程回归，未混入语言集。

下一步按 [执行协议](RELIABILITY_EVALUATION_PLAN.md) 确认新预算、核实实时单价、实现并验证持久预算和单次 Holdout runner，再运行 Dev 并最终冻结模型版本。当前命令没有 live 模式，防止误消耗 API 或提前使用保留集。RAG 暂不引入；先获得三轮可靠性变更后的真实模型证据。
