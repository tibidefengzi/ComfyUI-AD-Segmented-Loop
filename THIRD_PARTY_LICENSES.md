# 第三方许可与声明

## ComfyUI-H3-Latent-Relay 0.6.39

- 来源：https://github.com/ZenHG/ComfyUI-H3-Latent-Relay
- 版本/提交：0.6.39 / 054936a5313fe94902e2d7fd672754691beff320
- 许可：MIT
- 使用范围：本插件内嵌其节点层与核心算法层的所需子集，位于 `h3_loop/_relay_vendor/`；实际只注册桥接（CopyBridge）、潜桥存盘（LatentSave）、裁头（TrimAV）3 个节点，其余上游节点类不注册、不在画布/菜单暴露。
- 完整 MIT 许可证：`h3_loop/_relay_vendor/LICENSE-MIT.txt`
- 上游第三方通知：`h3_loop/_relay_vendor/THIRD-PARTY-NOTICES.md`

本插件整体按 GPL-3.0-only 分发；上述 MIT 代码保留原始版权与 MIT 许可声明。
