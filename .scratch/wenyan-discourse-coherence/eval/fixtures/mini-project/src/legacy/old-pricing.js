// old-pricing.js —— 已被 src/pricing.js 取代的旧定价实现
//
// 由 legacy-pricing-sdk 依赖驱动，团队已确认新的 src/pricing.js + src/cart.js 组合
// 完全替代了这里的逻辑。保留在仓库里只是历史遗留，尚未被删除。
const legacyPricingSdk = require('legacy-pricing-sdk');

function oldDiscountedTotal(items, discountRate) {
  return legacyPricingSdk.computeTotal(items, discountRate);
}

module.exports = { oldDiscountedTotal };
