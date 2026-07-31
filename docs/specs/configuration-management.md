# ScholarFlow 配置管理方案 Spec

> 版本: v1.0 | 日期: 2026-07-21 | 状态: ✅ 已实施（5 阶段全部完成）

---

## 1. 问题陈述



+         if not defined %%a set "%%a=%%b"
      )
  )
```

改动说明：`if not defined` 确保 `start.bat` 中已设置的变量不被 `.env` 覆盖。同时 `.env` 中 `HF_HUB_OFFLINE` 需改为 `1`。

---

## 7. 风险与回滚

| 风险 | 影响 | 缓解 |
|------|------|------|
| 工厂创建的 ChatModel 行为与原代码不同 | Agent 回答质量变化 | Phase 2 先在 deepseek 模式验证，与原 Agent 对比 |
| `RawLLMClient` 接口不覆盖所有 Ollama 参数 | think/keep_alive 等高级参数丢失 | 接口预留 `**kwargs` 透传 |
| `OllamaGenerator` 有 8 个调用方 | 遗漏某处未迁移 | grep 全项目 `OllamaGenerator` 确保 0 残留引用 |

回滚方式：每个 Phase 独立提交一个 commit，出问题直接 `git revert` 该 commit。
