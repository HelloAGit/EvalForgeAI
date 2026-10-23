# Changelog

All notable changes are documented here. Format: Keep a Changelog; versioning: SemVer.

## [Unreleased] - targeting v0.1.0
### Added
- Single-image Dockerfile (Next.js static export served by FastAPI), `.dockerignore`, Compose file.
- `/health` endpoint alias; CI and GHCR publish workflows; repository audit doc.
- Frontend build configuration and lockfile.
### Security
- Removed committed API keys from source, `.env.example` and Compose (keys must be rotated).
