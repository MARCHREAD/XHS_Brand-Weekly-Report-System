# Third-party components

This repository collects three independently developed platform projects. It does not assign a new blanket license to all imported code or to third-party assets.

| Component | Location | Notice |
| --- | --- | --- |
| Adapted `xhshow` signer | `platforms/xiaohongshu/collector/_signer/` | MIT; retain its [LICENSE](platforms/xiaohongshu/collector/_signer/LICENSE) and [original notice](platforms/xiaohongshu/THIRD_PARTY_NOTICES.md) |
| Douyin Webcast JavaScript signing helper | `platforms/douyin/vendor/douyin-live/` | Retain the [AGPL-3.0 license](platforms/douyin/vendor/douyin-live/LICENSE), [notice](platforms/douyin/vendor/douyin-live/NOTICE.md), and provenance file |
| Java / Python / Node dependencies | Each platform's requirements and build files | Resolved separately under their respective licenses |
| App packages, native libraries, official frontend / GT3 assets | Not distributed in this source import | Provision locally where needed; upstream assets remain the property of their respective owners |

Do not assume that a private working copy, a test fixture, or a source-code comment grants permission to redistribute an upstream binary. Keep notices alongside vendored code when moving directories.
