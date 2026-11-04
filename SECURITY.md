# Vaultie security status

Vaultie is an independent Windows Qt WebEngine browser. It has **not been
independently security-audited** and is **not certified as equivalent to Brave**.

## Current technical measures
- Qt WebEngine provides the underlying Chromium browser engine. Chromium
  security fixes are delivered through upstream Qt WebEngine packages and
  require a new Vaultie build; Qt version updates are not installed in place.
- Strictly local, opt-in credential storage using Windows DPAPI.
- Off-the-record profile: no persistent browsing cookies or WebEngine cache.
- First-party + third-party domain-based request blocking and tracking
  parameter removal.
- Limited fingerprint resistance: canvas readback perturbation and generic
  WebGL debugging strings, with reduced hardware concurrency / memory details.
  These are *best effort*, are not comprehensive, and can affect some sites.
- Startup release check: if a newer GitHub release is detected, Vaultie asks
  before opening the official installer download. **The unsigned installer is
  never installed automatically.**
- Each Windows build runs syntax/unit tests and a third-party vulnerability
  database scan of the installed Python packages.

## Remaining risks
- No independent penetration test or source-code audit has been performed.
- The installer is unsigned and does not include a publisher signature.
- The update downloader does not install security fixes unattended.
- Qt WebEngine does not include all Google Chrome services, including the
  Google Safe Browsing service (according to the Qt project).
- The JavaScript-based fingerprint modifications are not as comprehensive or
  tamper-resistant as browser-engine-level protections.
- Password autofill exposes credentials to JavaScript on the target origin,
  as with conventional browser autofill, and should not be used on untrusted
  websites.

## Reporting security findings
Report a security concern privately to the repository owner. Do not publish
passwords, recovery codes, or other secrets in public GitHub issues.
