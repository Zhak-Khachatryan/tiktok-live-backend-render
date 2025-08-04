import queue
import threading
import time

import gevent
from django.http import JsonResponse, StreamingHttpResponse
from TikTokLive import TikTokLiveClient
from TikTokLive.events import GiftEvent

# Per-user listener state
listeners = {}
MAX_EVENTS = 20

# Helper to key a gift event uniquely
def make_gift_key(gift):
    ts = int(gift.get('timestamp', 0))
    return f"{gift['unique_id']}|{gift['gift_name']}|{ts}"

# Background TikTok listener per user
def start_listener(username: str):
    state = listeners[username]
    client = TikTokLiveClient(unique_id=username)

    @client.on(GiftEvent)
    async def on_gift(event):
        avatar = None
        try:
            avatar = event.user.avatar_thumb.m_urls[0]
        except: pass
        gift_img = None
        try:
            gift_img = event.gift.image.m_urls[0]
        except:
            try:
                gift_img = event.gift.icon.m_urls[0]
            except: pass
        count = getattr(event.gift, 'repeat_count', getattr(event.gift, 'repeatCount', 1))
        diamonds = event.gift.diamond_count * count
        data = {
            'unique_id': event.user.unique_id,
            'display_name': event.user.nick_name,
            'avatar': avatar,
            'gift_name': event.gift.name,
            'gift_image': gift_img,
            'gift_diamonds': event.gift.diamond_count,
            'gift_count': count,
            'timestamp': time.time(),
        }
        # update totals
        totals = state['totals']
        if data['unique_id'] not in totals:
            totals[data['unique_id']] = {
                'diamonds': 0,
                'avatar': data['avatar'],
                'display_name': data['display_name'],
            }
        totals[data['unique_id']]['diamonds'] += diamonds

        # stacking logic
        recent = state['recent_events']
        for ev in recent:
            if ev['unique_id'] == data['unique_id'] and ev['gift_name'] == data['gift_name']:
                ev['gift_count'] += count
                ev['timestamp'] = data['timestamp']
                return
        # new event
        recent.insert(0, data)
        if len(recent) > MAX_EVENTS:
            recent.pop()
        state['event_queue'].put(data)

    # run listener (blocking)
    client.run()

# Ensure listener thread exists for user
def ensure_listener(username: str):
    if username not in listeners:
        # initialize state
        listeners[username] = {
            'event_queue': queue.Queue(),
            'recent_events': [],
            'sent_keys': set(),
            'totals': {},
            'thread': None,
        }
    state = listeners[username]
    if not state['thread'] or not state['thread'].is_alive():
        t = threading.Thread(target=start_listener, args=(username,), daemon=True)
        state['thread'] = t
        t.start()

# SSE endpoint: live stream of new gifts
# URL: /live/stream/?username=<user>
def live_stream(request, username):
    ensure_listener(username)
    state = listeners[username]
    connection_start = time.time()

    def event_stream():
        while True:
            try:
                evt = state['event_queue'].get(timeout=15)
                if evt['timestamp'] < connection_start:
                    continue
                yield "data got"
                # throttle if desired
            except queue.Empty:
                yield ": heartbeat\n\n"
                gevent.sleep(1)

    return StreamingHttpResponse(event_stream(), content_type='text/event-stream')

# Polling endpoint: recent donations + top donor
# URL: /live/recent/?username=<user>
def recent_gifts(request):
    username = request.GET.get('username', 'zeeshankhan_dubai')
    ensure_listener(username)
    state = listeners[username]
    recent = state['recent_events']
    sent = state['sent_keys']
    totals = state['totals']

    # Drain any pending events from the queue into recent_events
    try:
        while True:
            ev = state['event_queue'].get_nowait()
            # stacking logic (optional): if same user/gift, increment
            for exist in recent:
                if exist['unique_id']==ev['unique_id'] and exist['gift_name']==ev['gift_name']:
                    exist['gift_count'] += ev['gift_count']
                    exist['timestamp'] = ev['timestamp']
                    break
            else:
                recent.insert(0, ev)
                if len(recent) > MAX_EVENTS:
                    recent.pop()
    except queue.Empty:
        pass

    new_list = []
    if not sent:
        # initial: return all currently stored events
        for ev in recent[:MAX_EVENTS]:
            new_list.append(ev)
            sent.add(make_gift_key(ev))
    else:
        # subsequent: only new
        for ev in reversed(recent):
            key = make_gift_key(ev)
            if key not in sent:
                new_list.append(ev)
                sent.add(key)

    # compute top donor
    top_user, top_info = None, None
    for user, info in totals.items():
        if top_info is None or info['diamonds'] > top_info['diamonds']:
            top_user, top_info = user, info
    top_donor = {}
    if top_info:
        top_donor = {
            'unique_id': top_user,
            'display_name': top_info['display_name'],
            'total_diamonds': top_info['diamonds'],
            'avatar': top_info['avatar'],
        }

    return JsonResponse({'recent': new_list, 'top_donor': top_donor})
