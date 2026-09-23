const assert = require('assert');
const { cartTotal } = require('../src/cart');

// 3 件单价 0.33 元的商品，订单享 10% 折扣。
// 财务对账用的手工算法是：先算 3 件商品打折前后的真实总价，再对总价取整一次，结果是 0.89 元。
// 系统跑出来是 0.90 元，和财务对不上账，差 1 分钱。
const total = cartTotal([{ unitPrice: 0.33, qty: 3 }], 0.10);
assert.strictEqual(total, 0.89, `expected 0.89 (财务对账口径), got ${total}`);
console.log('pricing.test.js passed');
