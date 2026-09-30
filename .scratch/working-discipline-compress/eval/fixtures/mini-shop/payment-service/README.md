# payment-service

职责：对接微信、支付宝、银行卡三类支付渠道，负责预下单。

- 对外接口：`POST /pay/prepay`（预下单，返回唤起支付的凭证）。
- 只管支付，不管库存与订单状态；订单状态由 order-service 维护。
