from datetime import datetime
from utils import *
from django.db import models


class Game(models.Model):

    people = models.JSONField(default=list)  # [['p1name', 'p2name', 'spec_name', ..], [<p1ready>, <p2ready>]]
    status = models.IntegerField(default=ACTIVE)
    type = models.CharField()
    last_tick = models.DateTimeField(null=True)
    next_tick = models.IntegerField()
    gamestate = models.JSONField(default=dict)
    options = models.JSONField(default=dict)
    history = models.JSONField(default=list)  # [ [<keyframe>, <event>, ..], ..]
    chat_log = models.JSONField(default=list)

    def chat(self, user, message, timestamp=None):
        if not timestamp:
            timestamp = datetime.now()
        self.chat_log.append([timestamp.timestamp(), user, message])
        self.save()

    def event(self, type, info, timestamp=None):
        if not timestamp:
            timestamp = datetime.now()
        self.history[-1].append([type, info, timestamp.timestamp()])
        self.save()

    def keyframe(self):
        timestamp = datetime.now()
        self.history.append([['keyframe', self.gamestate, timestamp.timestamp()]])
        self.save()

    def response(self, prepared_gamestate, now, full=False):
        if not self.next_tick:
            duration = -1
            remaining = 0
        else:
            duration = self.next_tick
            remaining = duration - (now - self.last_tick).seconds
        return {
            'timer duration': duration,
            'time remaining': remaining,
            'gamestate': prepared_gamestate,
            'chat': self.chat[-50:],
            'options': self.options if full else {},
            'people': self.people[0],
        }

    def rewind(self, keyframes, reason):
        self.gamestate = self.history[-keyframes][1]
        if self.status == ACTIVE:
            now = datetime.now()
            self.last_tick = now
            self.next_tick = -1
            self.chat('system', reason, now)
            self.event('rewind', reason, now)
            self.keyframe()
        self.save()
