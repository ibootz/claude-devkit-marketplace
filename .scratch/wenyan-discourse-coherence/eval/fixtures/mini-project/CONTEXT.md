# mini-project 领域说明

这是一个虚构的购物车定价小项目，仅用于 wenyan-discourse-coherence 的行为评测固定文件，
不是真实产品代码。

## 术语

- **cartTotal**：购物车结算入口，输入商品行（单价 + 数量）与订单折扣率，输出应付总额。
  定义见 `src/cart.js`。
- **discountedUnitPrice**：单个商品按折扣率打折后的单价，取整到分。定义见 `src/pricing.js`。
- **CouponLedger**：优惠券登记簿，负责防止同一张优惠券在同一次结算里被重复应用；不负责
  校验优惠券是否过期或被禁用。定义见 `src/coupon-service.js`。
- **分（cent）精度**：本项目金额一律以分为最小单位取整，发票逐行金额与显示总价必须对得上。

## 已有决策

取整策略的决策记录见 `docs/adr/0001-rounding-strategy.md`。
