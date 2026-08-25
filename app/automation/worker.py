"""
Background automation worker.

Runs independently of any open browser tab — follow-ups fire whether or not the
owner is looking at the dashboard, which is the whole point of the product.
"""

import threading
import time
import traceback

from .. import config, db, repo


def sweep_once():
    """One pass: send every follow-up that is due. Returns how many went out."""
    from ..ai import engine

    sent = 0
    tenants = {}
    for lead in repo.leads_due_for_followup():
        tenant = tenants.get(lead["tenant_id"])
        if tenant is None:
            tenant = repo.get_tenant(lead["tenant_id"])
            tenants[lead["tenant_id"]] = tenant
        if not tenant or tenant["status"] in ("paused", "cancelled"):
            # Never message on behalf of a paused account.
            repo.update_lead(lead["tenant_id"], lead["id"], {"next_followup_at": None})
            continue
        try:
            sent += len(engine.run_followup(tenant, lead))
        except Exception:
            # One bad lead must not stop the sweep for everyone else.
            print(f"[worker] follow-up failed for lead {lead['id']}:")
            traceback.print_exc()
            repo.update_lead(lead["tenant_id"], lead["id"], {"next_followup_at": None})
    return sent


def _loop(stop_event):
    ticks = 0
    while not stop_event.is_set():
        stop_event.wait(config.WORKER_INTERVAL_SECONDS)
        if stop_event.is_set():
            break
        try:
            sent = sweep_once()
            if sent:
                print(f"[worker] sent {sent} automated follow-up(s)")
            ticks += 1
            if ticks % 30 == 0:
                repo.purge_expired_sessions()
        except Exception:
            print("[worker] sweep error:")
            traceback.print_exc()
    db.close_thread_connection()


def start():
    if not config.WORKER_ENABLED:
        print("[worker] disabled (WORKER_ENABLED=false)")
        return None
    stop_event = threading.Event()
    thread = threading.Thread(target=_loop, args=(stop_event,), daemon=True,
                              name="lil-automation")
    thread.start()
    print(f"[worker] automation running every {config.WORKER_INTERVAL_SECONDS}s")
    return stop_event
