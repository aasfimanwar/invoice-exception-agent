"""Render docs/POLICY.md from policy/policy.yaml. Never edit POLICY.md by hand (ADR-001)."""

from __future__ import annotations

from invoice_agent.policy_file import PolicyDict


def _money(value: float | None) -> str:
    return "no upper limit" if value is None else f"{value:,.2f}"


def render_policy_markdown(policy: PolicyDict) -> str:
    meta, par = policy["meta"], policy["parameters"]
    tax = policy["taxonomy"]
    out: list[str] = []
    w = out.append

    w(f"# {meta['organisation']} accounts payable exception policy")
    w("")
    w(f"*{meta['notice']}*")
    w("")
    w(f"Policy id `{meta['policy_id']}`, version {meta['version']}, status: {meta['status']}.")
    w("")
    w("**Generated from `policy/policy.yaml`. Do not edit by hand.**")
    w("")
    w("## 1. Purpose")
    w("")
    w(
        "This policy says how invoice and order exceptions are resolved, when software may act "
        "alone, and when a person must decide. Currency is GBP."
    )
    w("")
    w("## 2. Tolerances and limits")
    w("")
    w("| Parameter | Value |")
    w("|---|---|")
    price, qty = par["price"], par["quantity"]
    rows = [
        (
            "Rounding difference treated as rounding",
            f"{par['rounding_tolerance_gbp']:.2f} GBP per invoice",
        ),
        (
            "Price tolerance",
            f"{price['tolerance_pct_of_line']}% per line and "
            f"{price['tolerance_abs_per_invoice_gbp']:.2f} GBP per invoice",
        ),
        (
            "Price dispute threshold (no evidence of a price change)",
            f"more than {price['dispute_above_pct']}% on any line",
        ),
        (
            "Over-billing tolerance",
            f"{qty['over_billing_tolerance_pct_of_received']}% of received quantity and "
            f"{qty['over_billing_tolerance_abs_per_invoice_gbp']:.2f} GBP per invoice",
        ),
        (
            "Supplier name match",
            f"normalised similarity of {par['supplier']['name_match_min_ratio']} or better, "
            "or a registered alias",
        ),
        ("Exact duplicate window", f"{par['duplicate']['exact_window_days']} days"),
        ("Near-duplicate window", f"{par['duplicate']['near_duplicate_window_days']} days"),
        (
            "Partial delivery grace period",
            f"{par['partial_delivery']['grace_days_after_promised_date']} days after the "
            "promised date",
        ),
        ("Categories exempt from a PO", ", ".join(par["po_exempt_categories"])),
        (
            "Agent auto-approve limit (gross)",
            f"{par['autonomy']['agent_auto_approve_limit_gbp']:.2f} GBP",
        ),
        (
            "Confidence escalation threshold",
            "set from labelled development data in Phase 4 (not fixed by policy)",
        ),
    ]
    for name, value in rows:
        w(f"| {name} | {value} |")
    w("")
    w("## 3. Approver tiers (by gross invoice amount)")
    w("")
    w("| Tier | Up to (GBP) |")
    w("|---|---|")
    for tier in par["approver_tiers"]:
        w(f"| {tier['tier']} | {_money(tier['up_to_gbp'])} |")
    w("")
    d = par["urgency_days_to_due"]
    w("## 4. Urgency")
    w("")
    w(
        "Urgency is set by days from the case date to the due date: "
        f"critical when {d['critical']} days or fewer or overdue, "
        f"high when {d['critical'] + 1} to {d['high']} days, "
        f"normal when {d['high'] + 1} to {d['normal']} days, "
        f"low when more than {d['normal']} days."
    )
    w("")
    w("## 5. Actions")
    w("")
    for action, description in tax["actions"].items():
        w(f"- `{action}`: {description}")
    w("")
    w("## 6. Definitions")
    w("")
    for name, description in policy["predicates"].items():
        w(f"- **{name}**: {description}")
    w("")
    w("## 7. Resolution rules")
    w("")
    w(
        "Within each exception type the first matching rule applies. When a case shows several "
        "issues, the type highest in this list is primary: "
        + ", ".join(tax["precedence_when_multiple_issues"])
        + "."
    )
    w("")
    for exc_type, rules in policy["rules"].items():
        w(f"### {exc_type}")
        w("")
        w("| Rule | When | Action | Clause |")
        w("|---|---|---|---|")
        for rule in rules:
            when = " and ".join(rule["when"]) if rule["when"] else "otherwise"
            action = rule["action"]
            if action == "escalate":
                action = f"escalate ({rule['ambiguity']})"
            w(f"| {rule['id']} | {when} | {action} | {rule['text']} |")
        w("")
    w("## 8. Global controls")
    w("")
    for control in policy["global_controls"]:
        tag = "enforced in code" if control["enforced_in_code"] else "process rule"
        w(f"- **{control['id']}** ({tag}): {control['text']}")
    w("")
    return "\n".join(out)
