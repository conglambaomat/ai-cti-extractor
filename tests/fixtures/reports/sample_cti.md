# APT-EXAMPLE Threat Report — 2026-05-15

## Initial Access

The actor delivered a phishing email containing a malicious payload from
the C2 domain evil[.]com. The dropper connects to 185.220.101[.]45 over HTTPS.

## Indicators

The campaign uses the following infrastructure:

- IP: 45.33.32[.]156
- Domain: malicious[.]example[.]net
- SHA256: 3a7bd3e2360a3f83e0c6f1f01b4fdd7f4f8c9e8a5d4f3b2a1c0d9e8f7a6b5c4d
- CVE: CVE-2024-12345

Analysts should monitor for hxxps://evil[.]com/payload.exe and any beacons
back to the C2 domain malicious[.]example[.]net.
