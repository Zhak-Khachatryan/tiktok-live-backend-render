import queue
import threading
from django.http import StreamingHttpResponse
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent

# Thread-safe queue for gift events
EVENT_QUEUE = queue.Queue()


def start_tiktok_listener(username: str):
    """
    Connect to TikTok Live and enqueue every GiftEvent received.
    """
    client = TikTokLiveClient(unique_id=username)

    @client.on(GiftEvent)
    async def on_gift(event):
        # Enqueue event data tuple
        EVENT_QUEUE.put((event.user.nickname, event.gift.name, event.gift.repeat_count))

    # Start listening (blocks until disconnected)
    client.run()


# Ensure only one listener thread is started
_listener_thread = None


def ensure_listener(username: str):
    global _listener_thread
    if _listener_thread is None:
        _listener_thread = threading.Thread(
            target=start_tiktok_listener, args=(username,), daemon=True
        )
        _listener_thread.start()


def live_events(request):
    # Read TikTok username from query parameter or default
    username = request.GET.get("username", "parsl3y")
    # Start background listener once
    ensure_listener(username)

    def event_stream():
        # Continuously yield SSE-formatted gift events
        while True:
            user, gift_name, count = EVENT_QUEUE.get()  # blocks
            data = f"GIFT:{user}:{gift_name}:{count}"
            # SSE format requires 'data:' prefix and double newline separator
            yield f"data: {data}"

    # Return a streaming response with SSE
    return StreamingHttpResponse(event_stream(), content_type="text/event-stream")
