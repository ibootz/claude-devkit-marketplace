CREATE TABLE t_order (
  id               BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键',
  order_no         VARCHAR(32)  NOT NULL COMMENT '订单号',
  member_name      VARCHAR(64)  NOT NULL COMMENT '会员名称',
  status           TINYINT      NOT NULL COMMENT '订单状态，见 OrderStatus',
  pay_channel_mask INT          NOT NULL COMMENT '支付渠道位掩码，见 PayChannel',
  amount           BIGINT       NOT NULL COMMENT '金额，单位分',
  created_at       BIGINT       NOT NULL COMMENT '创建时间，毫秒时间戳，UTC',
  PRIMARY KEY (id),
  UNIQUE KEY uk_order_no (order_no)
) ENGINE=InnoDB COMMENT='订单表';
