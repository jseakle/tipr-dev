import functools, copy
import logging
from random import choice, shuffle
from tipr.utils import *
from tipr.rps_cards import *


ROUND_STRUCTURE = ['WRITE', 'CLARIFY', 'BET'] * 3 + ['REVEAL', 'BET', 'ADJUDICATE']

class LiarRules(object):

    keyframe_name = 'round'

    DEFAULT_OPTIONS = {
        'timed': False,
        'timer': 180,
        'player_count': 2,
    }

    def player_state(self, options):
        return {
            
        }

    def start_state(self, options):
        DECK = list(range(1,10)) * 5
        random.shuffle(DECK)
        starting_state = {
            'meta': {
                'round': 0,
                'message': ['Game Start']
            },
            # [{'text': "", 'votes': {'pN_True': [1, 0, 2], 'pN_False': [..],  ..}, 'truth': <bool>}, ..]. 'true' is absent until adjudicated.
            'statements': [],
            'revealed': [],
            'p1': {'hand': DECK[0:5], 'submission': {}}
            'p2': {'hand': DECK[5:10], 'submission': {}}
        }
        return starting_state

    def response(self, game, seat):
        return self.pure_response(Box(game.options), Box(game.gamestate), game.history, seat)

    def pure_response(self, options, gamestate, history, seat):
        del gamestate[opp(sets[seat])]
        return gamestate

    def should_update(self, game, gamestate, timestamp):
        return game.has_ticked(timestamp) or (gamestate.p1.submission and gamestate.p2.submission)
         
    def do_update(self, game):
        return self.pure_update(Box(game.options), Box(game.gamestate), game.history)

    def pure_update(self, options, gamestate, history):
        prev_state = copy.deepcopy(gamestate)
        last_round_type = ROUND_STRUCTURE[gamestate.meta.round]
        gamestate.meta.round += 1
        
        match last_round_type:
            case 'WRITE':
                p1_statement = gamestate.p1.submission or 'One equals one'
                p2_statement = gamestate.p2.submission or 'One equals one'                
                gamestate[statements].append({'text': p1_statement})
                gamestate[statements].append({'text': p2_statement})
            case 'BET':
                for seat in seats:
                    for statement_id, rest in gamestate.ga(seat).submission.items():
                        for yesno, amt in rest.items():
                            gamestate.statements[statement_id]['votes'][f'{seat}_{yesno}'].append(amt)
                if gamestate.meta.round == len(ROUND_STRUCTURE):
                    gamestate.meta.winner = self.winner(gamestate)
            case 'REVEAL':
                for seat in seats:
                    gamestate.revealed.append(gamestate.ga(seat).submission)

        gamestate.p1.submission = gamestate.p2.submission = {}

        return gen_delta(prev_state, gamestate)

    def winner(self, state):

        def score(player):
            total = 0
            for statement in state.statements:
                truth = statement.truth
                wins = sum(statement.votes.ga(f'{player}_{truth}'))
                enemy_losses = sum(statement.votes.ga(f'{opp(player)}_{not truth}'))
                total += wins * enemy_losses
            return total

        p1_score, p2_score = score('p1'), score('p2')
        if p1_score == p2_score:
            return None

        return 'p1' if p1_score > p2_score else 'p2'


    def move(self, game, seat, move):
        if not game.status == ACTIVE:
            return {'error': f'game is {game.status}'}
        gamestate = Box(game.gamestate)
        move = Box(move)
        seat = f"p{seat+1}"
        
        def invalid_statement(move):
            if not isinstance(move, str):
                return f"expecting a statement; got {repr(move)}"
            if move in filter(lambda stmt: stmt.text, gamestate.statements):
                return "don't submit an existing statement, that's boring"
    
        match ROUND_STRUCTURE[gamestate.meta.round]:
            case 'WRITE':
                if error := invalid_statement(move):
                    return {'error': error}
                gamestate.ga(seat).submission = move
            case 'CLARIFY':
                if 
