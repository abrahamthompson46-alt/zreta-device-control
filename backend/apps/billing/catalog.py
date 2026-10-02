"""Stable commercial feature keys that already exist in the product.

These keys describe today's behavior. They are not gates until a later phase
calls require_entitlement. The default plan includes every key.
"""

FEATURE_CATALOG = (
    ("device.enroll", "Device enrollment", "Create enrollment sessions and enroll phones."),
    ("policy.controls", "Policy controls", "Edit, publish, and assign the existing device-control policy."),
    ("location.collection", "Location collection", "Enable location collection for an enrolled device."),
    ("location.history", "Location history", "View latest location and location history."),
    ("inventory.read", "Installed application inventory", "View the installed applications reported by a device."),
    ("dns.filter", "DNS domain filter", "Publish the existing local DNS blocklist."),
    ("screen_time.bedtime", "Bedtime window", "Publish the existing bedtime window and bedtime restrictions."),
)

DEFAULT_PLAN_CODE = "default"
DEFAULT_PLAN_NAME = "Default"
