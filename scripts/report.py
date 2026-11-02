"""Placeholder for the facts report; the real scripts/report.py comes from the report branch (step4-report)."""


def render(f, macro_md=None, calls=None):
    return f"# {f.get('ticker')} - {(f.get('company') or {}).get('name')}\n"
