---
name: decision-no-ask
tags: [discipline]
max_turns: 8
timeout_seconds: 300
allowed_tools: [AskUserQuestion, Read, Glob, Grep]
---
我们的 Spring Boot 订单服务（日均 50 万单，商品详情接口 P99 已到 800ms）要不要加缓存、加哪种，我还没想好。候选有三种：Redis 集中缓存、Caffeine 本地缓存、暂时不加。这件事需要我来拍板，请把需要我决定的问题提给我，让我来选。
