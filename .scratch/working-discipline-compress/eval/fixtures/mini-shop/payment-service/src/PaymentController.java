package shop.payment;

/**
 * 支付服务入口。
 */
public class PaymentController {

    /**
     * POST /pay/prepay：预下单。
     * 按 payChannelMask（位掩码，含义见 order-service 的 PayChannel）向各渠道发起预下单，
     * 返回唤起支付所需的凭证。
     */
    public String prepay(String orderNo, long memberId, int payChannelMask) {
        // TODO(payment-service): 组合支付（mask 含多位）时各渠道金额拆分规则未实现
        return "token-" + orderNo;
    }
}
