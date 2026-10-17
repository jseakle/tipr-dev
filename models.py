from datetime import timedelta
from copy import deepcopy
from math import ceil
from .utils import ACTIVE, CREATED, Box, tznow, update
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
                                 'info': deepcopy(info),
                                 'timestamp': timestamp.timestamp()})
        self.save()

    def keyframe(self):
        timestamp = tznow()
        self.history.append([{'type': 'keyframe',
                              'info': deepcopy(self.gamestate),
                              'timestamp': timestamp.timestamp()}])
        self.save()

    # reinflate history at a non-keyframe point in time
    # interval_idx: keyframe to start from, as an index into the history list
    # count: number of states forward from keyframe to include. 0 = all for this keyframe.
    # last_only: just the specified state if True, all starting at keyframe if False
    @staticmethod
    def intermediate_states(history, interval_idx, count=0, last_only=False):
        try:
            # rewinds are part of linear history, but not part of blessed history. exclude them.
            interval = list(filter(lambda interval: 'rewound' not in interval[0], history))[interval_idx]
        # 
        except IndexError:
            return None
        frame = deepcopy(interval[0])
        if not last_only:
            ret = [deepcopy(frame)]
        if count == 0:
            count = len(interval)
        for i in range(1, count):
            if interval[i]['type'] == 'rewind':
                continue
            frame = update(frame, interval[i])
            if not last_only:
                ret.append(deepcopy(frame))
        if not last_only:
            return ret
        return Box(frame)

    def response(self, prepared_gamestate, now, full=False):
        if not self.last_tick:
            self.last_tick = now
            self.save(update_fields=['last_tick'])
        if self.status != ACTIVE:
            duration = 0
            remaining = 0
        elif self.next_tick is None or self.next_tick <= 0:
            duration = 0
            remaining = 0
        else:
            duration = self.next_tick
            remaining = max(0, ceil(duration - (now - self.last_tick).total_seconds()))
        return Box({
            'timer_duration': duration,
            'time_remaining': remaining,
            'gamestate': prepared_gamestate,  # has meta.deck = {'name': {type, stage, text}} if full
            'chat': self.chat_log,#[-50:],
            'options': self.options if full else {},
            'people': self.people[0],
        })

    def rewind(self, keyframes, reason):
        blessed_history = list(filter(lambda interval: 'rewound' not in interval[0], self.history))
        self.gamestate = deepcopy(blessed_history[-(keyframes+1)][0]['info'])
        for i in range(1, keyframes+1):
            self.history[-i][0]['rewound'] = True
        if self.status == ACTIVE:
            now = tznow()
            self.last_tick = now
            self.next_tick = -1
            self.chat('system', reason, now)
            self.event('rewind', reason, now)
        self.save()

    # this takes a timestamp instead of checking the time because we might be in a replay
    def has_ticked(self, timestamp):
        return (self.last_tick is not None and self.next_tick is not None
                and timestamp - self.last_tick >= timedelta(seconds=self.next_tick))
