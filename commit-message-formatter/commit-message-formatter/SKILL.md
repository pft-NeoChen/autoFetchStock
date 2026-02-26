---
name: commit-message-formatter
description: Guides the formatting of git commit messages according to specific project rules. Use this skill when asked to commit changes, draft commit messages, or prepare a PR wrap-up.
---

# Commit Message Formatter

When drafting git commit messages, you MUST adhere to the following format:

```text
<type>:<title>
[why]
<reasoning or context>
[how]
<implementation details>
```

## Allowed Types
- `feature`: New features or additions.
- `fix`: Bug fixes or corrections.
- `refinement`: Improvements, refactoring, or optimizations that aren't strict features or fixes.

## Examples

### Example 1: Single item
```text
feature:K線圖
[why] new feature
[how] k線圖開發
```

### Example 2: Multiple items (List)
```text
fix:
1. something wrong
2. UI wrong
[why] 
1. due to ooo
2. due to xxx
[how]
1. how I fix
2. I can fix
```
