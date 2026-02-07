"""In-app notification helpers for filing events."""


def create_filing_notifications(state_manager, filing_payloads, org_id):
    """Create one in-app notification per subscribed user per filing."""
    created = 0
    for payload in filing_payloads:
        ticker = payload.ticker if hasattr(payload, "ticker") else payload.get("ticker", "")
        accession_number = payload.accession_number if hasattr(payload, "accession_number") else payload.get("accession_number", "")
        filing_url = payload.filing_url if hasattr(payload, "filing_url") else payload.get("filing_url", "")
        subscribers = state_manager.list_watchlist_subscribers(org_id, ticker)
        for user_id in subscribers:
            title = "New %s filing detected" % ticker
            body = "A new filing (%s) was detected for %s. %s" % (accession_number, ticker, filing_url)
            state_manager.create_notification(
                org_id=org_id,
                user_id=user_id,
                ticker=ticker,
                accession_number=accession_number,
                notification_type="FILING_FOUND",
                title=title,
                body=body,
            )
            created += 1
    return created
