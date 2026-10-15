---
type: regex
target: trace
pattern: '"id":"(msg_[A-Za-z0-9]+)","type":"message","role":"assistant","content":\[\{"type":"tool_use"[\s\S]*?\n[^\n]*"id":"\1","type":"message","role":"assistant","content":\[\{"type":"tool_use"'
---
