# inventory-service

职责：管理 sku 的可售库存与预占库存。

- 对外接口：`POST /stock/deduct`（预占库存）、`POST /stock/rollback`（释放预占）。
- 预占库存不是出库：只减少可售数，到 `lock.ttl` 仍未被确认的预占会自动释放。
- 不关心订单状态与支付，只认订单号与 sku。
