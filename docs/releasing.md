# Releasing

EvalForgeAI uses [SemVer](https://semver.org). The first planned release is `v0.1.0`; it is not cut automatically.

## Image tagging policy (`ghcr.io/helloagit/evalforgeai`)
| Trigger | Tags |
|---|---|
| push to `main` | `latest`, `sha-<full commit sha>` |
| tag `vX.Y.Z` | `X.Y.Z`, `X.Y`, `sha-<full commit sha>` |
| manual dispatch | tags per the ref it runs on |

## Cutting a release
1. Update `CHANGELOG.md`; ensure CI is green on `main`.
2. `git tag v0.1.0 && git push origin v0.1.0` (after approval).
3. Confirm the *Publish GHCR image* workflow succeeded and the package appears at the package page.
4. Package visibility is private by default: set it in the package settings and link it to the repository.
