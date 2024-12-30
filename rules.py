from django.template.loader import render_to_string 
from tipr.utils import *
from django.core.cache import cache
import logging

class Rules(object):
    def winner(self, game):
        pass


    def render_gameboard(self, name, load, seat, game, gamestate, now):
        gameboard_context = self.gameboard_context(name, seat, game, gamestate, now)
        response = Box()
        response.gameboard = render_to_string(f'{game.type}_board.html', gameboard_context)
        response.timer = render_to_string('timer.html', gameboard_context)
        response.chat = render_to_string( 'chat.html', {'chat_log': game.chat_log})
        name = gameboard_context.name
        if not load and response.gameboard == cache.get(f'{name}_gameboard'):
            logging.warning('u')
            response.gameboard = 'U'
        else:
            cache.set(f'{name}_gameboard', response.gameboard)
        if not load and response.chat == cache.get(f'{name}_chat'):
            response.chat = 'U'
        else:
            cache.set(f'{name}_chat', response.chat)
        return response
