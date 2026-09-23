// cart.js —— 购物车结算入口
const { discountedUnitPrice } = require('./pricing');

// cartTotal：对每个商品行按折扣率打折（复用 discountedUnitPrice），乘数量后求和，
// 最后对总价再取整一次，返回应付总额。
function cartTotal(items, discountRate) {
  const rawTotal = items.reduce((sum, item) => {
    const perUnit = discountedUnitPrice(item.unitPrice, discountRate);
    return sum + perUnit * item.qty;
  }, 0);
  return Math.round(rawTotal * 100) / 100;
}

module.exports = { cartTotal };
