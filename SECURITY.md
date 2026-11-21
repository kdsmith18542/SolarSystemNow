# Security Policy

## Release verification

Release artifacts are checksummed and, when the signing secret is configured,
GPG-signed. Verify an AppImage with:

```bash
# 1. Import the release signing key (attached to each release)
gpg --import release-signing-key.asc

# 2. Verify the checksum signature
gpg --verify SHA256SUMS.asc SHA256SUMS

# 3. Verify the artifact
sha256sum -c SHA256SUMS
```

Release signing key fingerprint:

```
ACA74DC872549C4EC8FF0DF8D248D42F9842E3EA
```

The key is a dedicated signing-only ed25519 key ("Solar System Now Release
Signing <release@ss-now.local>"). It has no passphrase because it lives in the
CI repository secret used by `.github/workflows/ci.yml`; rotate it immediately
if the repository secret store is ever compromised.

## Runtime security posture

- The web API exposes **read-only GETs** publicly. All POST endpoints
  (`/api/ingest`, `/api/settings`, `/api/sim/run`) can be closed with the
  `SSNOW_API_TOKEN` environment variable; the desktop and web UI then send
  `X-SSNOW-Token`.
- The NASA API key is **write-only** over HTTP: GET `/api/settings` reports
  only whether a key is stored, never its value.
- The desktop in remote mode is read-only apart from the settings keys it is
  allowed to write (locations, tide stations, NASA key, retention).
- No telemetry is collected; all data comes from the public upstream sources
  listed in the app's Sources view.

## Reporting a vulnerability

Open a private security advisory via GitHub
(Security → Advisories → "Report a vulnerability") or email the maintainer.
Please do not open a public issue for undisclosed vulnerabilities.
