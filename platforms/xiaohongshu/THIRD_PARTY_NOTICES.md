# Third-party notices

This project includes an adapted copy of the MIT-licensed `xhshow` 0.2.0
implementation under `collector/_signer` for Xiaohongshu request signing.

- Project: https://github.com/Cloxl/xhshow
- License: MIT
- License copy: `collector/_signer/LICENSE`
- Responsibility boundary: the adapted implementation generates request signature headers; the collector owns HTTP transport, authentication state, pagination, normalization, persistence, API routes, and optional OpenAI enrichment.
