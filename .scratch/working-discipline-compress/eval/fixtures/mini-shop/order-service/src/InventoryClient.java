package shop.order;

/**
 * 库存服务客户端，超时见 application.yml 的 inventory.timeout。
 */
public class InventoryClient {

    /** 调 inventory-service：POST /stock/deduct，预占库存 */
    public void deduct(String orderNo, long skuId, int quantity) {
        throw new UnsupportedOperationException("fixture only");
    }

    /** 调 inventory-service：POST /stock/rollback，释放该订单预占的库存 */
    public void rollback(String orderNo) {
        throw new UnsupportedOperationException("fixture only");
    }
}
