from datetime import datetime
from tipr.utils import *
from django.db import models


class Game(models.Model):

    people = models.JSONField(default=list)  # [['p1name', 'p2name', 'spec_name', ..], [<p1ready>, <p2ready>]]
    status = models.IntegerField(default=CREATED)
    type = models.CharField(max_length=32)
    last_tick = models.DateTimeField(null=True)
    next_tick = models.IntegerField(null=True)
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

    def response(self, prepared_gamestate, now, full=False):
        if not self.next_tick:
            duration = -1
            remaining = 0
        else:
            duration = self.next_tick
            if not self.last_tick:
                self.last_tick = now
                self.save()
            remaining = duration - (now - self.last_tick).seconds
        return Box({
            'timer_duration': duration,
            'time_remaining': remaining,
            'gamestate': prepared_gamestate,  # has meta.deck = {'name': {type, stage, text}} if full
            'chat': self.chat_log[-50:],
            'options': self.options if full else {},
            'people': self.people[0],
        })

    def rewind(self, keyframes, reason):
        self.gamestate = self.history[-keyframes][0]['info']
        if self.status == ACTIVE:
            now = tznow()
            self.last_tick = now
            self.next_tick = -1
            self.chat('system', reason, now)
            self.event('rewind', reason, now)
            self.keyframe()
        self.save()
