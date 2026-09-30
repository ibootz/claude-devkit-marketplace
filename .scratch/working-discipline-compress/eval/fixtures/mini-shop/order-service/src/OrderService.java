package shop.order;

import shop.order.OrderController.CreateOrderRequest;
import shop.order.OrderController.CreateOrderResponse;

/**
 * 下单主流程。
 * <p>
 * 预占库存：下单时先在库存服务里给这笔订单锁住对应数量的库存（不是真正出库），
 * 锁有有效期（见 inventory-service 的 lock.ttl），到期未确认会自动释放。
 */
public class OrderService {

    private final InventoryClient inventoryClient;
    private final PaymentClient paymentClient;

    public OrderService(InventoryClient inventoryClient, PaymentClient paymentClient) {
        this.inventoryClient = inventoryClient;
        this.paymentClient = paymentClient;
    }

    public CreateOrderResponse create(CreateOrderRequest request) {
        String orderNo = generateOrderNo();

        // 第一步：预占库存，失败直接抛异常，订单不落库
        inventoryClient.deduct(orderNo, request.skuId, request.quantity);

        // 第二步：向支付服务预下单，拿到唤起支付用的凭证
        String prepayToken;
        try {
            prepayToken = paymentClient.prepay(orderNo, request.memberId, request.payChannelMask);
        } catch (RuntimeException e) {
            // 预下单失败：回滚第一步预占的库存，再把异常抛给调用方
            inventoryClient.rollback(orderNo);
            throw e;
        }

        CreateOrderResponse resp = new CreateOrderResponse();
        resp.orderNo = orderNo;
        resp.prepayToken = prepayToken;
        return resp;
    }

    private String generateOrderNo() {
        return "SO" + System.currentTimeMillis();
    }
}
