`tests/pricing.test.js` 是红的，根因在 `src/pricing.js` 与 `src/cart.js` 之间的取整链路
（细节见 `docs/adr/0001-rounding-strategy.md`）。

这件事需要我来拍板才能往下走：是现在就改 `src/cart.js` 去掉总价层的取整，还是先摸清楚
所有调用方再动手。不要用弹窗式的工具向我提问，直接在这段回复里把问题问清楚，我看完文字
就能回答。
