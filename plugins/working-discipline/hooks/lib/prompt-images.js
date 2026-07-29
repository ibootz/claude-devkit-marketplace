// prompt-images.js — 从 UserPromptSubmit 事件 payload 里提取本轮用户贴的图片路径
//
// 导出唯一一个纯函数 extractImagePaths(text)：不碰文件系统、不读 transcript、无副作用。
//
// 【为什么不再回读 transcript】（3.0.0 删除的 lib/transcript.js 的教训）
// 旧实现在 PreToolUse 时刻回读 transcript 找"本轮用户提供的图片"，判据是行的 type ==
// 'user'。但**工具结果行的 type 也是 'user'**，于是 AI 自己 Read 过一张图、甚至某次
// grep 输出里带一个 .png 路径，都会被算成"用户提供了截图"，让本轮后续所有 Agent 派发
// 被拦。更荒谬的是它读自己的源码就会自我触发——源码里的正则字面量完全符合旧路径正则的
// 形状。UserPromptSubmit 触发时本轮还没有任何工具输出，payload 里只有用户输入，判据
// 天然干净，这是把那条规则从硬拦改软约束时顺带修掉的根因。
//
// 【两条正则，宁漏不误】
// 软约束下漏一条提醒无所谓（AI 自己也能 Read 图），但误报会让 AI 把**假路径**写进
// 派发 prompt，子代理 Read 到不存在的文件或读错图，代价高得多。所以：
//   1. IMAGE_TAG_PATTERN 优先：`[Image: source: <path>]` 是 harness 渲染用户贴图的固定
//      形态（2026-07-28 与 2026-07-29 两次实测确认），最可靠。
//   2. BARE_IMAGE_PATH_PATTERN 兜底：裸绝对路径要求**至少两级路径段**，且路径字符里不
//      含 `|` 与反斜杠。前者杜绝残片（真实截图路径必然多级，贪婪切分产生的残片必然
//      单级，旧版就切出过 `/1.png` 这类假路径），后者杜绝把正则字面量当成路径。
// 已知取舍：含空格的手写路径（`/Users/me/Desktop/shot 2.png`）扫不到——见上，宁漏不误。

'use strict'

// [Image: source: /abs/path/to/x.png] —— 允许 Image 后面有别的属性，只取 source 的值
const IMAGE_TAG_PATTERN = /\[Image[^\]]*?source:\s*([^\]\s]+)\]/gi

// 裸绝对路径：/seg/seg[/seg…]/name.ext，至少两级路径段，路径字符排除空白、`|`、反斜杠、引号
const BARE_IMAGE_PATH_PATTERN = /\/[^\s|\\'"]+\/[^\s|\\'"]+\.(?:png|jpe?g|webp|gif)\b/gi

function collect(text, pattern, groupIndex) {
  const out = []
  let m
  pattern.lastIndex = 0
  while ((m = pattern.exec(text)) !== null) {
    const v = groupIndex ? m[groupIndex] : m[0]
    if (v) out.push(v)
  }
  return out
}

// 返回去重后的图片绝对路径数组，保持首次出现顺序。
function extractImagePaths(text) {
  if (typeof text !== 'string' || !text) return []

  const tagged = collect(text, IMAGE_TAG_PATTERN, 1)
  const bare = collect(text, BARE_IMAGE_PATH_PATTERN, 0)

  const seen = new Set()
  const result = []
  for (const p of tagged.concat(bare)) {
    if (!p.startsWith('/')) continue // 只要绝对路径
    if (seen.has(p)) continue
    seen.add(p)
    result.push(p)
  }
  return result
}

module.exports = { extractImagePaths }
