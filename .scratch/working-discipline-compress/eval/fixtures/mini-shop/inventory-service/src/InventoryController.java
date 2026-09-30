package shop.inventory;

/**
 * 库存服务入口。
 */
public class InventoryController {

    /**
     * POST /stock/deduct：预占库存。
     * 预占库存 = 给订单锁住 quantity 件库存，可售数减少但实物未出库；
     * 锁的有效期见 application.yml 的 lock.ttl（毫秒）。
     */
    public void deduct(String orderNo, long skuId, int quantity) {
        // TODO(inventory-service): 并发扣减目前靠行锁，热点 sku 会排队
    }

    /**
     * POST /stock/rollback：释放该订单预占的库存，幂等。
     */
    public void rollback(String orderNo) {
    }
}
