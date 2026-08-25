"""
Plan catalogue.

Prices live in the database and are edited from the agency console — nothing in
the app or on the landing page hardcodes a price. These are only the values the
catalogue is seeded with on first boot.
"""

from .. import repo

DEFAULT_PLANS = [
    {
        "slug": "starter", "name": "Starter",
        "setup_cents": 100000, "monthly_cents": 100000, "sort_order": 1, "highlight": False,
        "features": [
            "Instant AI response to every lead",
            "Automated qualification & follow-up",
            "Appointment booking",
            "Lead dashboard & conversations",
            "Email notifications",
            "1 lead source connected",
        ],
    },
    {
        "slug": "growth", "name": "Growth",
        "setup_cents": 150000, "monthly_cents": 150000, "sort_order": 2, "highlight": True,
        "features": [
            "Everything in Starter",
            "Unlimited lead sources & webhooks",
            "SMS notifications",
            "Custom qualification questions",
            "Full reporting suite",
            "Priority support",
        ],
    },
    {
        "slug": "pro", "name": "Pro",
        "setup_cents": 250000, "monthly_cents": 250000, "sort_order": 3, "highlight": False,
        "features": [
            "Everything in Growth",
            "Multi-location support",
            "Custom AI instructions & tone",
            "CRM / API integrations",
            "Dedicated onboarding",
            "Quarterly performance review",
        ],
    },
]


def ensure_default_plans():
    """Idempotent: only seeds when the catalogue is empty, so edited prices are
    never overwritten on restart."""
    if repo.list_plans(active_only=False):
        return repo.list_plans(active_only=False)
    for plan in DEFAULT_PLANS:
        repo.upsert_plan(**plan)
    return repo.list_plans(active_only=False)
