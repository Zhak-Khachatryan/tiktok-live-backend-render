from django.http import StreamingHttpResponse
import asyncio
from TikTokLive import TikTokLiveClient
from TikTokLive.events import CommentEvent, GiftEvent

def live_events(request):
    username = request.GET.get('username', 'YOUR_TIKTOK_USERNAME')
    client = TikTokLiveClient(unique_id=username)

    # Create new event loop for this request
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    queue = asyncio.Queue()

    async def start_stream():
        @client.on(CommentEvent)
        async def on_comment(event):
            await queue.put(f"data: COMMENT:{event.user.nickname}:{event.comment}")

        @client.on(GiftEvent)
        async def on_gift(event):
            await queue.put(f"data: GIFT:{event.user.nickname}:{event.gift.name}:{event.gift.repeat_count}")

        # Connect to TikTok Live (blocks until disconnected)
        await client.connect()

    # Launch TikTok listener in background
    loop.create_task(start_stream())

    def event_stream():
        try:
            while True:
                # Wait for next message from queue
                msg = loop.run_until_complete(queue.get())
                yield msg
        finally:
            # Clean up when client disconnects or request ends
            loop.stop()
            loop.close()

    return StreamingHttpResponse(event_stream(), content_type='text/event-stream')