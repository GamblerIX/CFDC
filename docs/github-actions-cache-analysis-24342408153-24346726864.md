# GitHub Actions 缓存分析（Run 24342408153 与 24346726864）

## 结论

`24346726864` 没有加载到你期望的“上一轮（24342408153）已翻译进度缓存”，根因是：

1. 工作流把缓存主键设置为 `translation-cache-${{ github.run_id }}`，每次运行都是新 key。
2. `actions/cache` 的保存动作发生在 **Post Restore translation cache**（后置阶段）。
3. `24342408153` 被手动取消后，后置保存步骤被跳过（job step 显示 `Post Restore translation cache ... skipped`），因此该 run 的增量缓存从未上传。
4. 于是 `24346726864` 在 restore 时只能匹配到更早（若存在）的 `translation-cache-` 前缀缓存，而不是 24342408153 的最新进度。

## 证据

- 工作流缓存配置：
  - `key: translation-cache-${{ github.run_id }}`
  - `restore-keys: translation-cache-`
- Job 24342408153 步骤状态：
  - `Restore translation cache`：success
  - `Run resumable translation`：cancelled
  - `Post Restore translation cache`：skipped

以上行为与 `actions/cache` 的机制一致：**取消运行不会保证 post-step 上传缓存**。

## 建议

1. **不要手动取消**翻译任务；改为让脚本通过 `--max-runtime-minutes` 正常退出，这样 post-step 能执行并上传缓存。
2. 若需要“随时可中断且可恢复”的能力，建议改为：
   - 周期性把 `pythonplaywrightstealth/cache` 打包上传到 artifact（但被强制取消时同样可能来不及上传）；或
   - 把中间进度写入外部持久化存储（如分支文件、对象存储）。
3. 保留当前 `run_id` 作为缓存 key 的设计是合理的（避免 immutable key 冲突）；核心问题不是 key 设计，而是“取消导致未保存”。
