# API 清单与操作契约

完整机器可读契约：`docs/openapi.json`；运行时交互文档：`http://127.0.0.1:8000/docs`。

除 health 外，业务接口必须传本地演示身份，具体见 README。表中“客户”均需对象归属检查，管理员可查询全体演示用户。

| 方法 | 路径 | 身份 | 说明 |
|---|---|---|---|
| GET | /health | 无 | DB 已初始化且可访问为 200，否则 503 |
| GET | /users/{user_id} | 客户/管理员 | 用户信息 |
| GET | /users/{user_id}/orders | 客户/管理员 | 用户订单 |
| GET | /orders/{order_id} | 客户/管理员 | 金额、状态、时间 |
| GET | /orders/{order_id}/items | 客户/管理员 | 商品行与分摊金额 |
| GET | /orders/{order_id}/shipment | 客户/管理员 | 物流；未发货为 null |
| GET | /orders/{order_id}/refunds | 客户/管理员 | 退款记录，缺少记录为空列表 |
| GET | /tickets | 客户/管理员 | 工单列表，可选 status/limit/offset |
| GET | /tickets/{ticket_id} | 客户/管理员 | 工单详情 |
| POST | /tickets | 客户/管理员 | 创建工单，201 |
| PATCH | /tickets/{ticket_id}/order | 客户/管理员 | 给缺订单工单补关联 |
| PATCH | /tickets/{ticket_id}/status | 管理员 | 无活跃动作时进行合法状态转移 |
| POST | /policy/evaluate | 客户/管理员 | 只读预览，不预留额度 |
| POST | /actions | 客户/管理员 | 政策校验、预留、创建必要审批；幂等返回 200 |
| GET | /actions/{action_id} | 客户/管理员 | 申请、政策与执行状态 |
| GET | /tickets/{ticket_id}/actions | 客户/管理员 | 工单历次动作 |
| GET | /approvals | 管理员 | 可选 status/limit/offset |
| GET | /approvals/{approval_id} | 管理员 | 审批详情 |
| POST | /approvals/{approval_id}/review | 管理员 | approve 布尔值和 reason |
| POST | /actions/{action_id}/return-receipt | 管理员 | 收货 note；重复不重复计数 |
| POST | /actions/{action_id}/simulate-execution | 管理员 | outcome: SUCCESS/FAILURE，默认 SUCCESS |
| GET | /actions/{action_id}/audit | 管理员 | 政策、审批、收货、执行审计 |

上表为 Stage 1–2 的 22 个操作。Stage 3 新增 6 个 Agent 操作，总计 28 个，见 [STAGE3.md](STAGE3.md)。另有框架提供的 docs/redoc/openapi 路由。没有可以传入任意金额或直接设置退款成功的公开 API。

## 请求示例

创建工单：

```json
{"user_id":3,"order_id":1003,"issue_type":"NO_REASON_RETURN","description":"申请退回一件"}
```

提交商品退货申请（ticket_id 替换为上一步返回值）：

```json
{"ticket_id":4,"proposed_action":"RETURN_AND_REFUND","order_item_id":10031,"quantity":1,"evidence_provided":false,"idempotency_key":"return-1003-001"}
```

创建缺订单工单时省略 order_id。补充后调用 `/tickets/{id}/order`，请求 `{"order_id":1001}`。商品信息或证据不足时，使用同一工单和新幂等键重新提交完整 ActionCreate；原申请保留。

量值语义：`order_item_id` 与 `quantity` 必须同时提供，或同时缺失以得到“信息不足”。整单动作不允许带商品字段。所有 JSON 多余字段都拒绝，包括 `amount`、`status`、`final_action`、`reviewer`。

## 错误契约

```json
{"error":{"code":"ACTION_NOT_READY","message":"动作仍需审批、收货或补充信息，不能执行","request_id":"..."}}
```

响应头 `X-Request-Id` 与错误体一致，可关联本地日志。422 不回显提交的输入；500 不返回 traceback。400 系列用于身份、字段或资源错误；409 用于状态、幂等或数据冲突；503 用于数据库未就绪或锁等待等可重试异常。

业务政策拒绝本身仍是成功处理请求，HTTP 200，检查 `decision=DENY`。已发货取消等场景可能将建议动作替换为物流调查，检查 `authorized_action`，不要只读 `proposed_action`。

## 幂等细节

幂等键在每个用户内唯一，长度 8–128，仅允许字母数字与 `_.:-`。相同键和相同请求返回现有 ActionRequest；相同键不同请求返回 409。

执行成功后重复执行返回原结果；失败后重复 FAILURE 返回原失败；FAILED 后 SUCCESS 尝试重试并重验政策。审批相同结果重试返回原审核记录；不能反向更改已完成审批。

Stage 3 已给 POST /tickets 增加可选 `Idempotency-Key` 请求头（8–128 字符）。相同用户同键同参返回同一工单，不同请求返回 409；不传头时保持 Stage 1–2 每次创建的行为。Agent 始终使用服务器生成的稳定工单/动作键。
