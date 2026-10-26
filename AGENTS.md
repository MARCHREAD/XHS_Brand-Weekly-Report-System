# Repository conventions

- Keep each platform under `platforms/xiaohongshu`, `platforms/douyin`, or `platforms/bilibili` with independent dependencies, configuration, tests, and README.
- Do not mix account state or move platform modules to the repository root.
- Never commit credentials, captured authenticated traffic, runtime databases, private device profiles, or generated build directories.
- Keep Douyin's user-facing workbench at `127.0.0.1:8779`; update in place rather than launching additional preview ports. Other platform defaults are documented in their own README.
- Run offline validation from the affected platform's directory. Tests must not silently become live collection or real message sending.
- Update root navigation and the affected platform README when capabilities or startup requirements change.
