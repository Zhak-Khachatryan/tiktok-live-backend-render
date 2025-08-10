import json
import logging
import queue

import gevent
from asgiref.sync import sync_to_async
from django.db import close_old_connections, connection, transaction
from django.db.models import F
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent

from .models import Donator, Gift

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("TikTokLive").setLevel(logging.DEBUG) 

listeners = {}
MAX_EVENTS = 20


def start_listener(username: str):
    """
    Background thread: runs TikTok client and processes incoming GiftEvent.
    It writes DB rows (Donator/Gift) and enqueues a small payload into
    listeners[username]['event_queue'] for any SSE client.
    """
    # get/ensure state exists (ensure_listener sets up state but keep safe)
    connection.close()
    close_old_connections()
    state = listeners.get(username)
    client = TikTokLiveClient(unique_id=username)

    @client.on(GiftEvent)
    async def on_gift(event):
        # extract raw event info
        unique_id = event.user.unique_id
        avatar = getattr(event.user.avatar_thumb, "m_urls", [None])[0]

        gift_name = event.gift.name
        gift_image = getattr(getattr(event.gift, "image", None) or getattr(event.gift, "icon", None), "m_urls", [None])[0]
        count = getattr(event.gift, "repeat_count", getattr(event.gift, "repeatCount", 1))
        diamonds = event.gift.diamond_count * count
        print(diamonds, event.gift.diamond_count, count)

        # Do DB work on a thread via sync_to_async. We encapsulate sync logic in a function.
        def _process_db():
            close_old_connections()
            # use a transaction for consistency
            with transaction.atomic():
                # get or create donator using unique_id (unique key)
                donator, created = Donator.objects.get_or_create(
                    username=unique_id,
                    defaults={"user_image": avatar, "diamonds": 0},
                )
                # atomic increment of diamonds and refresh avatar
                Donator.objects.filter(pk=donator.pk).update(
                    diamonds=F("diamonds") + diamonds,
                    user_image=avatar,
                )
                # retrieve updated donator for later use
                donator.refresh_from_db()

                # find existing unread gift for this donator + name
                # If exists, atomically increment fields; else create a new Gift
                existing = Gift.objects.filter(user=donator, gift_name=gift_name, read=False).first()
                if existing:
                    Gift.objects.filter(pk=existing.pk).update(
                        gift_count=F("gift_count") + count,
                        diamonds=F("diamonds") + diamonds,
                        # we cannot update timestamp with F(); set after refresh below
                    )
                    existing.refresh_from_db()
                    existing.timestamp = timezone.now()
                    existing.read = False
                    existing.save(update_fields=["timestamp", "read"])
                    gift_obj = existing
                else:
                    gift_obj = Gift.objects.create(
                        user=donator,
                        gift_name=gift_name,
                        gift_image=gift_image,
                        gift_count=count,
                        diamonds=diamonds,
                        read=False,
                    )

            return {
                "donator_id": donator.pk,
                "donator_username": donator.username,
                "donator_avatar": donator.user_image,
                "gift_id": gift_obj.pk,
                "gift_name": gift_obj.gift_name,
                "gift_image": gift_obj.gift_image,
                "gift_count": gift_obj.gift_count,
                "gift_diamonds": gift_obj.diamonds,
                "timestamp": gift_obj.timestamp.timestamp(),
            }

        try:
            result = await sync_to_async(_process_db)()
        except Exception:
            logger.exception("DB processing failed for gift event")
            return

        # prepare payload for SSE or other consumers
        payload = {
            "donator_username": result["donator_username"],
            "donator_avatar": result["donator_avatar"],
            "gift_id": result["gift_id"],
            "gift_name": result["gift_name"],
            "gift_image": result["gift_image"],
            "gift_count": result["gift_count"],
            "gift_diamonds": result["gift_diamonds"],
            "timestamp": result["timestamp"],
        }

        # enqueue for any subscriber (safe because state is plain dict/populated by ensure_listener)
        try:
            if state is None:
                # fallback: try to get live state if not captured earlier
                s = listeners.get(username)
            else:
                s = state
            if s:
                # non-blocking put, but queue has no maxsize so this should not block
                s["event_queue"].put(payload)
        except Exception:
            logger.exception("Failed to enqueue event payload")


    # run listener (blocking) — keep that in a loop so if client.run() raises the thread will retry
    while True:
        try:
            client.run()
        except Exception as ex:
            logger.exception(f"Listener for {username} crashed: {ex} — retrying in 5s")
            gevent.sleep(5)


def ensure_listener(username: str):
    if username not in listeners:
        listeners[username] = {
            "event_queue": queue.Queue(),
            "recent_events": [],
            "sent_keys": set(),
            "totals": {},
            "thread": None,
        }
    state = listeners[username]
    if not state["thread"] or getattr(state["thread"], "dead", False):
        g = gevent.spawn(start_listener, username)
        state["thread"] = g


# SSE endpoint (if you still want it) — now uses proper SSE framing and non-blocking queue checks
def live_stream(request, username):
    ensure_listener(username)
    state = listeners[username]

    def event_stream():
        try:
            while True:
                try:
                    evt = state["event_queue"].get_nowait()
                    payload = json.dumps(evt)
                    # proper SSE framing: data: <payload>\n\n
                    yield f"data: {payload}\n\n"
                except queue.Empty:
                    # heartbeat as SSE comment; keep a small sleep to avoid tight loop
                    yield ": heartbeat\n\n"
                    gevent.sleep(0.5)
        except GeneratorExit:
            # client disconnected — generator will be closed
            return
        except Exception:
            logger.exception("Error in event_stream")
            return

    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")


# Polling endpoint (improved)
def recent_gifts(request):
    close_old_connections()

    # limit and optimize with select_related to avoid per-row user queries
    gifts_qs = Gift.objects.filter(read=False).order_by("timestamp").select_related("user")[:MAX_EVENTS]
    gifts_list = list(gifts_qs)  # evaluated
    gift_ids = [g.id for g in gifts_list]

    recent = [
        {
            "username": g.user.username,
            "avatar": g.user.user_image,
            "gift_name": g.gift_name,
            "gift_image": g.gift_image,
            "gift_count": g.gift_count,
            "diamonds": g.diamonds,
            "timestamp": g.timestamp.timestamp(),
        }
        for g in gifts_list
    ]

    # mark read in one bulk update
    if gift_ids:
        Gift.objects.filter(id__in=gift_ids).update(read=True)

    # top Donator (descending diamonds)
    top_donor = Donator.objects.order_by("-diamonds").first()
    top = {}
    if top_donor:
        top = {
            "username": top_donor.username,
            "avatar": top_donor.user_image,
            "total_diamonds": top_donor.diamonds,
        }

    return JsonResponse({"recent": recent, "top_donor": top})
