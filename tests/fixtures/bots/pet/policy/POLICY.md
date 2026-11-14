---
name: pet-policy
description: 宠物照护的业务操作指导策略
top_k: 5
---

## pet-selection

- User: 帮我安排宠物的日常照护
- Bot:
  - Thought: 先明确日常照护需求，使用 pet-care，根据真实用户信息决定是否追问。
  - Skills: pet-care
  - Thought: 宠物类型或照护目标尚不明确时，直接询问最相关的信息，不重复询问已回答的问题。
  - Reply: 你养的是什么宠物？

## pet-cancel

- User: 先不弄了
- Bot:
  - Thought: 尊重用户取消，停止当前追问并简短回应，不继续强行收集宠物资料。
  - Reply: 好的，需要时再来找我。
