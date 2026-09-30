package shop.order;

/**
 * 支付渠道，位掩码：t_order.pay_channel_mask 是下面各常量按位或之后的值，
 * 一个订单可以组合支付。
 * <p>
 * 1=微信 2=支付宝 4=银行卡
 * <p>
 * 例：mask=3 表示微信 + 支付宝；mask=6 表示支付宝 + 银行卡。
 */
public final class PayChannel {
    public static final int WECHAT = 1;
    public static final int ALIPAY = 2;
    public static final int BANK_CARD = 4;

    private PayChannel() {
    }

    public static boolean has(int mask, int channel) {
        return (mask & channel) != 0;
    }
}
