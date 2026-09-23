// coupon-service.js —— CouponLedger
//
// CouponLedger：记录本次结算已经用过的优惠券编码，防止同一张券在同一次结算里被重复应用。
// 不做优惠券是否过期、是否被禁用的校验 —— 那是 pricing 层的职责，本类只管"这次用过没有"。
class CouponLedger {
  constructor() {
    this._used = new Set();
  }

  // 尝试登记一张券；返回 false 表示这张券本次已经用过，调用方应跳过应用折扣。
  tryApply(couponCode) {
    if (this._used.has(couponCode)) return false;
    this._used.add(couponCode);
    return true;
  }

  reset() {
    this._used.clear();
  }
}

module.exports = { CouponLedger };
