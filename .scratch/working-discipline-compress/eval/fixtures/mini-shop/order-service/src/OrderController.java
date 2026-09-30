package shop.order;

/**
 * 订单入口。
 */
public class OrderController {

    private final OrderService orderService;

    public OrderController(OrderService orderService) {
        this.orderService = orderService;
    }

    /**
     * POST /orders：创建订单。
     * 请求体带会员、商品、数量、支付渠道；返回订单号与预下单凭证。
     */
    public CreateOrderResponse createOrder(CreateOrderRequest request) {
        // TODO(order-service): 请求体校验目前只判空，没有校验 quantity 上限
        return orderService.create(request);
    }

    public static class CreateOrderRequest {
        public long memberId;
        public long skuId;
        public int quantity;
        public int payChannelMask;
    }

    public static class CreateOrderResponse {
        public String orderNo;
        public String prepayToken;
    }
}
