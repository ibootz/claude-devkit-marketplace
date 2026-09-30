package shop.order;

/**
 * 订单状态，对应 t_order.status 列。
 * <p>
 * 1=待支付 2=已支付 3=已发货 4=已完成 9=已取消
 * <p>
 * 履约单：订单进入「已支付」后由仓储侧生成的发货工作单，一个订单对应一张履约单，
 * 状态从 2 走到 3（已发货）以履约单出库为准。
 */
public enum OrderStatus {
    PENDING_PAY(1),
    PAID(2),
    SHIPPED(3),
    COMPLETED(4),
    CANCELLED(9);

    private final int code;

    OrderStatus(int code) {
        this.code = code;
    }

    public int getCode() {
        return code;
    }
}
