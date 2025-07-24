import queue
import threading
from django.http import StreamingHttpResponse
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent

# Global queue to hold incoming gift events
EVENT_QUEUE = queue.Queue()

def start_tiktok_listener(username: str):
    client = TikTokLiveClient(unique_id=username)
    @client.on(GiftEvent)
    async def on_gift(event):
        # Put gift event data into the queue
        EVENT_QUEUE.put(event)
    # Run the client (blocks)
    client.run()

# Start the TikTok listener thread once
THREAD_STARTED = False
def ensure_thread(username):
    global THREAD_STARTED
    if not THREAD_STARTED:
        thread = threading.Thread(target=start_tiktok_listener, args=(username,), daemon=True)
        thread.start()
        THREAD_STARTED = True

def live_events(request):
    # Get TikTok username from query, or default
    username = request.GET.get('username', 'parsl3y')
    # Ensure background listener is running
    ensure_thread(username)

    def event_stream():
        while True:
            event = EVENT_QUEUE.get()  # blocks until a gift arrives
            # Format SSE message
            yield f"data: GIFT:{event.user.nickname}:{event.gift.name}:{event.gift.repeat_count}"

    return StreamingHttpResponse(event_stream(), content_type='text/event-stream')
