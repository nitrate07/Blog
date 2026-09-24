# Deferred Findings

Out-of-scope findings intentionally **not** addressed when they surfaced — real, but not worth derailing the task they
were found in. Captured here so they don't slip into "I'll remember." Severity reflects "impact if left ~6 months," not
"broken today." See `RULES.md` §7 for the capture protocol.

<!-- Template for new entries (self-allocating slug ID — never a sequential number; RULES §10.1):

### deferred:<kebab-slug> — <short title>
- **Subject**: <tags: system / vendor / component the finding is about>
- **Where**: <file / location>
- **What**: <the issue>
- **Severity**: <Low | Medium | High>
- **Suggested fix**: <actionable suggestion>
- **Why deferred**: <why it was safe to skip now>
-->

## How this file is maintained
1. When you fix one: delete its entry, and reference the stable slug ID in the fixing commit (`closes deferred:<slug>`).
2. When you discover a NEW out-of-scope risk during related work: prompt me (RULES §7), and if I agree, add it here —
   don't let it slip into chat.
3. When something here becomes urgent (impact observed): promote it to a real ticket and link back.
