// pricing.js —— 单件商品的折扣计算
//
// discountedUnitPrice：按订单折扣率给单价打折，取整到分。
// 取整发生在这一层是 ADR 0001 的既定决策（见 docs/adr/0001-rounding-strategy.md）。
function discountedUnitPrice(unitPrice, discountRate) {
  const discounted = unitPrice * (1 - discountRate);
  return Math.round(discounted * 100) / 100;
}

module.exports = { discountedUnitPrice };
