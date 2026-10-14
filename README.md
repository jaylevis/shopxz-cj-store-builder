# shopxz-cj-store-builder

Agent skill that builds a **fulfillable** ShopXZ / Fecify catalog from CJ Dropshipping products for a Japanese B2C store,
so the store is GMC-ready from day one (real stock, tracked shipping to Japan, truthful policies).

Pipeline (read-only until the manager skill's gated import):

```text
auth -> profile -> discover (fulfillability gate) -> select -> enrich-tasks (host AI writes Japanese copy)
     -> enrich-apply (validation) -> images (WebP + optional AI re-shoot) -> export -> phase1 (manager validation)
     -> merchant confirmation -> import via fecify-site-manager-v6 -> collections / policies / emails / recall
```

Requires `fecify-site-manager-v6` (store API, image provider, WebP tooling) and Python 3.10+ / Node 18+.
CJ credentials are read from `%LOCALAPPDATA%/Fecify/cj/cj.env` (`CJ_EMAIL`, `CJ_API_KEY`) or `FECIFY_CJ_ENV`; nothing
secret is stored in this repository. See [SKILL.md](SKILL.md).
