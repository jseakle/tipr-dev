from datetime import timedelta
from tipr.utils import *
from django.db import models


class Game(models.Model):

    people = models.JSONField(default=list)  # [['p1name', 'p2name', 'spec_name', ..], [<p1ready>, <p2ready>]]
    status = models.IntegerField(default=CREATED)
    type = models.CharField(max_length=32)
    last_tick = models.DateTimeField(null=True)
    next_tick = models.IntegerField(null=True)  # seconds from last_tick
    gamestate = models.JSONField(default=dict)
    options = models.JSONField(default=dict)
    history = models.JSONField(default=list)  # [ [<keyframe>, <event>, ..], ..]
    chat_log = models.JSONField(default=list)

    def chat(self, user, message, timestamp=None):
        if not timestamp:
            timestamp = tznow()
        self.chat_log.append([timestamp.timestamp(), user, message])
        self.save()

    def event(self, type, info, timestamp=None):
        if not timestamp:
            timestamp = tznow()
        self.history[-1].append({'type': type,
                                 'info': info,
                                 'timestamp': timestamp.timestamp()})
        self.save()

    def keyframe(self):
        timestamp = tznow()
        self.history.append([{'type': 'keyframe',
                              'info': self.gamestate,
                              'timestamp': timestamp.timestamp()}])
        self.save()

    # interval_idx: keyframe to start from, as an index into the history list
    # count: number of states forward from keyframe to include. 0 = all for this keyframe.
    @staticmethod
    def intermediate_states(history, interval_idx, count=0, last_only=False):
        try:
            interval = list(filter(lambda interval: 'rewound' not in interval[0], history))[interval_idx]
        except IndexError:
            return None
        frame = interval[0]
        if not last_only:
            ret = [frame]
        if count == 0:
            count = len(interval)
        for i in range(1, count):
            frame = update(frame, interval[i])
            if not last_only:
                ret.append(frame)
        if not last_only:
            return ret
        return Box(frame)

    def response(self, prepared_gamestate, now, full=False):
        if not self.last_tick:
            self.last_tick = now
            self.save()
        if self.status != ACTIVE:
            duration = 0
            remaining = 0
        elif not self.next_tick:
            duration = 0
            remaining = 0
        else:
            duration = self.next_tick
            remaining = duration - ((now - self.last_tick).seconds) #round(duration - ((now - self.last_tick).seconds + (now - self.last_tick).microseconds / 1000000), 2)
            if remaining <= 0:
                remaining = 1
        return Box({
            'timer_duration': duration,
            'time_remaining': remaining,
            'gamestate': prepared_gamestate,  # has meta.deck = {'name': {type, stage, text}} if full
            'chat': self.chat_log,#[-50:],
            'options': self.options if full else {},
            'people': self.people[0],
        })

    def rewind(self, keyframes, reason):
        self.gamestate = self.history[-keyframes][0]['info']
        for i in range(keyframes):
            self.history[-i][0]['rewound'] = True
        if self.status == ACTIVE:
            now = tznow()
            self.last_tick = now
            self.next_tick = -1
            self.chat('system', reason, now)
            self.event('rewind', reason, now)
            self.keyframe()
        self.save()

    # this takes a timestamp instead of checking the time because we might be in a replay
    def has_ticked(self, timestamp):
        return timestamp - self.last_tick > timedelta(seconds=self.next_tick)
