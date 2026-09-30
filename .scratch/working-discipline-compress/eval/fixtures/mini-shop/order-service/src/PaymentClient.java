package shop.order;

/**
 * 支付服务客户端，超时见 application.yml 的 payment.timeout（单位秒）。
 */
public class PaymentClient {

    /** 调 payment-service：POST /pay/prepay，预下单，返回唤起支付的凭证 */
    public String prepay(String orderNo, long memberId, int payChannelMask) {
        throw new UnsupportedOperationException("fixture only");
    }
}
