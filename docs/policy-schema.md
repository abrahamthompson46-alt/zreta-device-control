# Policy schema

## Phase 4.1 — Domain foundation (implemented)

Additive Django app `apps.policies` provides organization-scoped policy storage.

### Models

| Model | Purpose |
|---|---|
| `Policy` | Named policy container per organization. Active (non-archived) names are unique within an organization; archived policies may share a name with a new active policy. |
| `PolicyVersion` | Versioned JSON `document` with `schema_version`, `version_number`, `status` (`draft` / `published` / `superseded` / `archived`), and optional `content_hash`. Unique `(policy, version_number)`. At most one `published` version per policy. `PROTECT` on the policy FK so historical versions are not cascade-deleted. Non-draft documents are immutable at the model layer. |
| `DevicePolicyAssignment` | One-to-one device binding to a `Policy`, with optional `pinned_version`. Organization must match both device and policy; a pinned version must belong to that policy (validated in `clean()`). Assignment services are not implemented yet. |

## Phase 4.2 — Validation and lifecycle (implemented)

Backend services in `apps.policies` are authoritative for schema validation and publication. No parent/device APIs, Android cache, acknowledgement, dashboard UI, schedules, or enforcement.

### Schema version 1

A publishable document must be a JSON object with **exactly** these top-level keys:

```json
{
  "schema_version": 1,
  "internet": {},
  "calls": {},
  "applications": {},
  "screen_time": {},
  "device": {},
  "location": {}
}
```

Rules:

- Top-level value must be an object.
- `schema_version` must be the integer `1` (only supported version).
- All six section keys are required; each section value must be an object.
- Unknown top-level keys are **rejected** (not stripped).
- Empty section objects are valid and mean no enforcement for that section.
- Serialized size must not exceed `POLICY_DOCUMENT_MAX_BYTES` (default 65536).

### Phase 4.7 — applications / device fields (additive within schema v1)

`applications` may include only:

- `suspend_packages`: array of Android package name strings
- `hide_packages`: array of Android package name strings
- `uninstall_blocked_packages`: array of Android package name strings

`device` may include only:

- `camera_disabled`: boolean
- `screen_capture_disabled`: boolean

Unknown keys under these sections are rejected.

### Phase 4.8 — calls / internet / screen_time / location fields (additive within schema v1)

`calls` may include only:

- `block_outgoing_calls`: boolean → Device Owner `DISALLOW_OUTGOING_CALLS`
- `block_sms`: boolean → `DISALLOW_SMS`

`internet` may include:

- `disallow_config_wifi`: boolean
- `disallow_config_mobile_networks`: boolean
- `disallow_config_tethering`: boolean
- `disallow_config_vpn`: boolean
- `traffic` (optional object, Phase 5.1A foundation):
  - `enabled`: boolean
  - `engine`: must be exactly `local_dns_blocklist`
  - `blocked_domains`: array of hostname strings (normalized lowercase, deduped, sorted)

Traffic limits: max 500 domains, max 253 chars per domain, max 8192 total characters.

Matching semantics (for the future VpnService in 5.1B): a lookup host `Q` is blocked if it equals a blocked domain `B` or is a subdomain of `B` (`Q == B` or `Q.endsWith("." + B)`). No wildcards.

Rejected in `traffic`: `always_on`, `lockdown`, unknown keys, IP literals, schemes/paths/ports, empty labels.

**Phase 5.1B status:** local `DnsFilterVpnService` implements disclosed, fail-open, DNS-only VpnService filtering (narrow routes, NXDOMAIN for blocked names, UDP upstream with `protect()`). Not always-on / lockdown. TCP DNS, DoH, and DoT are out of scope for this slice. Physical-device validation remains mandatory.
`screen_time` may include only (best-effort bedtime windows; **no** `lockNow`, **no** UsageStats daily limits):

- `bedtime_start` / `bedtime_end`: `HH:MM` local time (both required together; **must differ** — equal values are rejected)
- `bedtime_block_outgoing_calls`: boolean (requires window)
- `bedtime_suspend_packages`: package name array (requires window)

End time is exclusive (e.g. `06:00` means inactive at 06:00).

`location` may include only:

- `collection_desired`: boolean — **advisory only**. Does not enable GPS or override Phase 3 `Device.location_collection_enabled`.

Drafts may store incomplete documents; **publication** always runs full validation.

### Canonical hash

`content_hash` is `sha256:` plus the hex digest of the canonical UTF-8 JSON:

- `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
- Only the policy document is hashed (not names, assignments, or audit metadata).

Implemented in `apps.policies.canonical` and used for size checks and publish.

### Lifecycle

| Operation | Behavior |
|---|---|
| Create draft | New `version_number` (max+1 under policy row lock); status `draft`; optional deep copy from an existing version. |
| Edit draft | Only `draft` versions; replaces document; never mutates other versions. |
| Publish | Atomic: `select_for_update` on Policy → validate → canonicalize → hash → prior `published` becomes `superseded` → draft becomes `published` with `published_at` / `published_by` / `content_hash`. |
| Rollback | Creates a **new** draft (deep copy of the target document) and publishes it. Historical versions are never rewritten. |

Organization ownership is checked on every service call (caller organization must own the policy/version). Cross-organization operations fail.

### Audit

- `policy.version_created`
- `policy.published`
- `policy.superseded`

Snapshots include policy/version ids, version_number, schema_version, status, and content_hash when present — **never** the full document.

### Compatibility

`Device.location_collection_enabled` remains the Phase 3 authority for location collection. `DeviceStatus.applied_policy_version` is unchanged.

## Phase 4.4 — Device policy pull and acknowledgement (implemented)

- `GET /api/v1/device/policy` — Device JWT; effective policy for the authenticated device only; `ETag` / `If-None-Match`.
- `POST /api/v1/device/policy/ack` — Device reports applied/rejected result; updates additive `DeviceStatus` fields (`applied_policy_version_ref`, `policy_applied_at`, ack metadata) without renaming `applied_policy_version`.
- Android: encrypted `PolicyCache`, `PolicyWorker` (15m), schema v1 fail-closed validation, last-known-good retained on malformed/unassigned.
- Dashboard: list/create/publish/assign policies (no section enforcement UI).

Heartbeat/`me` may include additive `policy_version_number` and `policy_assignment_state` hints (not authoritative transport).

### Phase 4.7 — first enforcement slice (Android)

Android Device Owner enforcement for `applications` (suspend / hide / uninstall-block) and `device` (camera / screen capture), with local managed-state bookkeeping. ACK may report additive telemetry results `enforcement_partial` / `rejected_enforcement` without updating applied version fields.

### Phase 4.8 — remaining section enforcement (Android)

- **Calls / internet:** Device Owner **user-restriction** slice only (`DISALLOW_OUTGOING_CALLS` / `DISALLOW_SMS` / config wifi·mobile·tether·vpn). **Not** packet/firewall filtering, per-app network blocking, DNS filtering, or always-on VPN lockdown.
- **Screen time:** **Bedtime/window** enforcement only (local `HH:MM`, exclusive end). **Not** a UsageStats daily screen-time budget. `bedtime_start` and `bedtime_end` must differ. On PolicyWorker HTTP **304**, if the cached LKG has time-dependent controls, the worker re-runs the **same** `PolicyCompliance` / `PolicyEnforcer` path against that LKG with the current clock (document is not rewritten). Re-evaluation is still **best-effort** and subject to WorkManager scheduling/OEM delay.
- **Location:** `LocationPolicyAdapter` records `collection_desired` as **advisory only**; Phase 3 `location_collection_enabled` remains authoritative.

### Still not implemented

FCM, PolicySchedule, wipe/kiosk, always-on VPN lockdown, UsageStats daily screen limits, physical-device verification.
