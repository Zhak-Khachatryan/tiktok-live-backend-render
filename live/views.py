import json
import queue
import threading
import time

from django.http import JsonResponse, StreamingHttpResponse
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent

# Thread-safe queue for gift events
event_queue = queue.Queue()
listener_thread = None
recent_events = []  # in-memory store of recent gifts
MAX_EVENTS = 20

def start_listener(username: str):
    """
    Background listener: connects to TikTok Live and enqueues GiftEvent data.
    Retries on failure to maintain connection.
    """
    while True:
        client = TikTokLiveClient(unique_id=username)

        @client.on(GiftEvent)
        async def on_gift(event):
            try:
                count = event.gift.repeat_count
            except AttributeError:
                # Fallback if attribute differs or single gift
                count = getattr(event.gift, 'repeatCount', 1)  # noqa: F841
            data = {
                'username': event.user.nick_name,
                'profile_picture': event.user.profile_picture.url_list[0],
                'gift': event.gift.name,
                'gift_image': event.gift.image.url_list[0],
                'gift_diamonds': event.gift.diamond_count,
                'gift_count': count,
                'ts': time.time(),
            }
            # log to console
            print('Received gift:', data)
            # enqueue for SSE
            event_queue.put(data)
            # store in recent events
            recent_events.insert(0, data)
            if len(recent_events) > MAX_EVENTS:
                recent_events.pop()

        try:
            client.run()
        except Exception as e:
            print(f"Listener error: {e}")
            time.sleep(5)
            continue
        break

def ensure_listener(username: str):
    """
    Starts the background listener thread if not already running.
    """
    global listener_thread
    if listener_thread is None or not listener_thread.is_alive():
        listener_thread = threading.Thread(
            target=start_listener,
            args=(username,),
            daemon=True
        )
        listener_thread.start()

def live_events(request):
    """
    SSE endpoint streaming GiftEvent data as JSON.
    Use `?username=<tiktok_user>` to specify stream.
    """
    username = request.GET.get('username', 'davidcrossland4')
    ensure_listener(username)

    def event_stream():
        while True:
            try:
                event = event_queue.get(timeout=15)
                payload = json.dumps(event)
                # SSE format: data:<payload>


                yield f"data: {payload}"
            except queue.Empty:
                # heartbeat to keep SSE alive
                yield ": heartbeat"
                time.sleep(1)

    return StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )

def recent_gifts(request):
    """
    Returns the most recent gifts as JSON.
    """
    return JsonResponse(recent_events, safe=False)