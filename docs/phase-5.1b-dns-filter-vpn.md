# Phase 5.1B — Local DNS filter VPN runtime

## Architecture

```
PolicyWorker → PolicyCache/LKG → PolicyEnforcer → InternetTrafficEnforcer
  → VpnDnsFilterController → DnsFilterVpnService (VpnService)
       → DnsFilterEngine + DnsTunPacketHandler + UdpDnsUpstream
```

The VPN runtime never fetches policy and never authenticates to the backend.
It only receives already-validated canonical domain lists from enforcement.

## Routing (narrow DNS-only)

| Item | Value |
|---|---|
| TUN IPv4 | `10.255.255.2/32` |
| Synthetic DNS IPv4 | `10.255.255.1` via `addDnsServer` + route `10.255.255.1/32` |
| TUN IPv6 | `fd00:5a74::2/128` |
| Synthetic DNS IPv6 | `fd00:5a74::1` via `addDnsServer` + route `fd00:5a74::1/128` |
| Full tunnel | **Not used** — no `0.0.0.0/0` or `::/0` |

Non-DNS traffic stays on the underlying network. Management HTTP (OkHttp) is not routed into the TUN because there is no default route through the VPN.

## DNS behavior

- Parse classic UDP DNS queries (single question, IN class).
- Blocked (exact/parent match via `DomainBlocklist`): **NXDOMAIN** (RCODE=3), QR=1, question preserved, no answers. Transaction ID preserved.
- Allowed: forward UDP DNS to upstream (`8.8.8.8` / `1.1.1.1`) on a `protect()`ed `DatagramSocket`.
- **TCP DNS / DoH / DoT**: not implemented in this slice (documented gap).
- Malformed / non-DNS TUN packets: ignored (fail-open).
- No domain/query/payload logging by default.

## Consent

`VpnService.prepare()` is checked before start. If a consent `Intent` is returned, the controller returns `vpn_consent_required` / PARTIAL and does **not** launch UI from `PolicyWorker`.

## Readiness

RUNNING is signaled only after: TUN `establish()`, upstream `protect()` probe succeeds, and the packet loop thread is started. Foreground notification is required while running.

## Fail-open

Protect failure, establish failure, revoke, loop exit → stop filter, underlying network remains available, no false APPLIED. Always-on and lockdown are not implemented.

## Always-on opt-out

Manifest meta-data on `DnsFilterVpnService`:

```xml
<meta-data
    android:name="android.net.VpnService.SUPPORTS_ALWAYS_ON"
    android:value="false" />
```

Android defaults this to `true` if absent (API 27+). Phase 5.1B explicitly opts out so Settings / Device Owner cannot treat this service as always-on. No `setAlwaysOnVpnPackage` / `setLockdownVpnPackage` calls are used.

## Reboot gap

This slice does not add BOOT_COMPLETED VPN reconciliation. A reboot may leave the filter down until the next policy enforce cycle (and user consent if required).

## Background FGS start

`PolicyWorker` may call `startForegroundService` from a background WorkManager context. On Android 12+, that can throw `ForegroundServiceStartNotAllowedException`. The controller maps this to `vpn_fgs_start_not_allowed`, remains fail-open (PARTIAL), and never reports APPLIED.
