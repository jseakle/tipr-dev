import functools, copy, json
import logging
from termcolor import colored as c
from random import choice, shuffle
from tipr.utils import *
from tipr.rps_cards import *
from tipr.rules import Rules

ROUND_STRUCTURE = ['START'] + ['WRITE', 'CLARIFY', 'BET'] * 3 + ['REVEAL', 'BET', 'ADJUDICATE', 'DONE']

class LiarRules(Rules):

    keyframe_name = 'round'

    DEFAULT_OPTIONS = {
        'timed': False,
        'timer': 180,
        'player_count': 2,
        'fps': 8,
    }

    def player_state(self, options):
        return {
            
        }

    def start_state(self, options):
        starting_state = {
            'meta': {
                'round': 0,
                'message': ['Game Start']
            },
            # Even statements are p1s, odd statements are p2s
            # [{'text': "", 'votes': {'pN_True': [1, 0, 2], 'pN_False': [..],  ..}, 'truth': <bool>}, ..]. 'truth' is absent until adjudicated.
            'statements': [],
            'revealed': [],
            # SUBMISSION FORMATS
            # WRITE: str
            # CLARIFY: [<unclear statementid>]
            # BET: {<statementid>: (<stmt is true or false: bool>, int)}
            # REVEAL: int
            # ADJUDICATE: [<false statementid>]

            'p1': {'hand': [], 'submission': None, 'to_revise': None, 'lies': 0},
            'p2': {'hand': [], 'submission': None, 'to_revise': None, 'lies': 0},
        }
        return starting_state

    def response(self, game, seat):
        return self.pure_response(Box(game.options), Box(game.gamestate), game.history, seat)

    def pure_response(self, options, gamestate, history, seat):
        # del gamestate[opp(seats[seat])]
        return gamestate

    def should_update(self, game, gamestate, timestamp):
        both = None not in (gamestate.p1.submission, gamestate.p2.submission)
        if game.next_tick == -1:
            return game.status == ACTIVE and both
        if timed := (game.status == ACTIVE and game.has_ticked(timestamp)):
            logging.warn(c('TIMED', 'red'))
        return game.status == ACTIVE and (timed or both)

    def winner(self, gamestate):
        if gamestate.meta.round == len(ROUND_STRUCTURE) - 1:
            s1, s2 = gamestate.p1.score, gamestate.p2.score
            if s1 == s2:
                return f'{s1} - {s1}: Tie game!'
            elif s1 > s2:
                return f'{s1} - {s2}: p1 wins!'
            else:
                return f'{s1} - {s2}: p2 wins!'
         
    def do_update(self, game):
        return self.pure_update(Box(game.options), Box(game.gamestate), game.history)

    def pure_update(self, options, gamestate, history):
        prev_state = copy.deepcopy(gamestate)
        last_round_type = ROUND_STRUCTURE[gamestate.meta.round]
        if last_round_type != 'DONE':
            gamestate.meta.round += 1
        
        # Process round that just ended
        match last_round_type:
            case 'START':
                DECK = list(range(1,10)) * 5
                shuffle(DECK)
                gamestate.p1.hand = DECK[0:5]
                gamestate.p2.hand = DECK[5:10]
                logging.warning(f"{gamestate.p1.hand} {gamestate.p2.hand} XXXXX")

            case 'WRITE':
                p1_statement = gamestate.p1.submission or 'One equals one'
                p2_statement = gamestate.p2.submission or 'One equals one'                
                gamestate.statements.append({'text': p1_statement, 'votes': {f'{seat}_{truth}': [] for seat in seats for truth in ['true', 'false']}})
                gamestate.statements.append({'text': p2_statement, 'votes': {f'{seat}_{truth}': [] for seat in seats for truth in ['true', 'false']}})

            case 'CLARIFY':
                wrong_ids = list(map(int, set(gamestate.p1.submission) | set(gamestate.p2.submission)))
                if wrong_ids:
                    gamestate.meta.message.append("Players marked one or more statements as ambiguous, try again!")
                    for id in [len(gamestate.statements) - 1, len(gamestate.statements) - 2]:
                        if id % 2 == 0:
                            if id in wrong_ids:
                                gamestate.p1.submission = gamestate.statements[-2]
                            else:
                                gamestate.p1.to_revise = gamestate.statements[-2]
                        else:
                            if id in wrong_ids:
                                gamestate.p2.submission = gamestate.statements[-1]
                            else:
                                gamestate.p2.to_revise = gamestate.statements[-1]
                    gamestate.meta.round -= 2
                    gamestate.statements = gamestate.statements[:-2]

            case 'BET':
                for seat in seats:
                    submission = gamestate.ga(seat).submission
                    for statement_id in range(len(gamestate.statements)):
                        for truth in ['true', 'false']:
                            amt = 0
                            if submission and (sid := submission.get(str(statement_id))):
                                amt = sid.get(truth, 0)
                            gamestate.statements[statement_id]['votes'][f'{seat}_{truth}'].append(amt)
                    logging.warning(f'BETS {seat}: {gamestate.statements}')
                            
            case 'REVEAL':
                for seat in seats:
                    sub = gamestate.ga(seat).submission
                    if sub is None:
                        sub = int(choice(gamestate.ga(seat).hand))
                    else:
                        sub = int(sub)
                    if sub not in gamestate.ga(seat).hand:
                        gamestate.ga(seat).lies += 1
                    gamestate.revealed.append(sub)
                    
            case 'ADJUDICATE':
                if gamestate.p1.submission != gamestate.p2.submission:
                    gamestate.meta.message.append("Players disagreed about one or more statements, try again!")
                    gamestate.meta.round -= 1
                else:
                    def score(player):
                        total = 0
                        for i, statement in enumerate(gamestate.statements):
                            truth = str(i) in gamestate.p1.submission
                            statement.truth = truth
                            wins = sum(statement.votes.ga(f"{player}_{json.dumps(truth)}"))
                            enemy_losses = sum(statement.votes.ga(f'{opp(player)}_{json.dumps(not truth)}'))
                            total += (1 + wins) * (1 + enemy_losses)
                        total -= gamestate.ga(player).lies * 2
                        
                        return total

                    gamestate.p1.score, gamestate.p2.score = score('p1'), score('p2')

        # Process upcoming round
        match ROUND_STRUCTURE[gamestate.meta.round]:
            case 'WRITE':
                gamestate.meta.message.append("Submit a true or false statement pertaining only to the total set of numbers in both players' hands.")
            case 'CLARIFY':
                gamestate.meta.message.append("Mark each submission as clear or ambiguous")
            case 'BET':
                gamestate.meta.message.append("Bet up to N chips on True or False for statements in row N")
            case 'REVEAL':
                gamestate.meta.message.append("Reveal a value from your hand, or lie at the cost of 2 points")
            case 'ADJUDICATE':
                gamestate.meta.message.append("Mark each statement as True or False")
                
        gamestate.p1.submission = None
        gamestate.p2.submission = None
        gamestate.p1.to_revise = gamestate.p2.to_revise = None

        patch = gen_patch(prev_state, gamestate)
        logging.warn(c(f'^ UPDATE {patch}', 'red'))
        return patch


    def move(self, game, seat, move):
        if not game.status == ACTIVE:
            return {'error': f'game is {game.status}'}
        gamestate = Box(game.gamestate)
        seat = f"p{seat+1}"
        
        def invalid_statement(move):
            if not isinstance(move, str):
                return f"expecting a statement; got {repr(move)}"
            if move in filter(lambda stmt: stmt.text, gamestate.statements):
                return "don't submit an existing statement, that's boring"
            if len(move) > 140:
                return "that's too long."
    
        match ROUND_STRUCTURE[gamestate.meta.round]:
            case 'WRITE':
                if error := invalid_statement(move):
                    return {'error': error}
                gamestate.ga(seat).submission = move
                
            case 'CLARIFY' | 'ADJUDICATE':
                logging.warn(move)
                gamestate.ga(seat).submission = move
                
            case 'BET':
                move_dict = move
                if type(move_dict) != dict:
                    return {'error': "invalid dict, something's wrong"}
                for statementid, votes in move_dict.items():
                    cap = int(statementid) // 2 + 1 + (1 if gamestate.meta.round == 11 else 0)
                    if any(filter(lambda amt: amt > cap or amt < 0, votes.values())):
                        return {'error': f"you bet an invalid amount somehow: {votes} stmt {statementid} cap {cap}"}
                gamestate.ga(seat).submission = move_dict

            case 'REVEAL':
                try:
                    move = int(move)
                except TypeError:
                    return {'error': f"expecting a card value to reveal, got {repr(move)}"}
                gamestate.ga(seat).submission = move

        return gen_patch(Box(game.gamestate), gamestate)

    def next_tick(self, game):
        round = ROUND_STRUCTURE[game.gamestate['meta']['round']] 
        logging.warning(f"{round}: {game.options['timer']}")
        if round == 'START':
            return 0
        if round in ('CLARIFY', 'ADJUDICATE'):
            return -1
        return game.options['timer']

    def gameboard_context(self, request, seat, game, gamestate, now):
        response = Box()
        gameboard_context = game.response(self.response(game, seat), now)
        gameboard_context.name = request.session.get('name')
        gameboard_context.p1_name = game.people[0][0] if len(game.people[0]) else 'p1'
        gameboard_context.p2_name = game.people[0][1] if len(game.people[0]) > 1 else 'p2'
        gameboard_context.active = game.status == 1
        gamestate = Box(gameboard_context.gamestate)
        gameboard_context.seat = ('p1', 'p2', 'spectating')[seat]
        gameboard_context.hand = gamestate.ga(seats[seat]).hand
        round = ROUND_STRUCTURE[gamestate.meta.round]
        if round in ['ADJUDICATE', 'DONE']:
            gameboard_context.opp_hand = gamestate.ga(opp(seat)).hand
        prev = ROUND_STRUCTURE[gamestate.meta.round - 1]
        gameboard_context.textinput = round in ['WRITE', 'REVEAL']
        gameboard_context.bet = round == 'BET'
        gameboard_context.showdown = round in ['DONE', 'ADJUDICATE']
        gameboard_context.done = round in ['DONE']
        logging.warning(f'FFF {gamestate.statements}')
        gameboard_context.columns = [{'player': gameboard_context.p1_name, 'statements': [(gamestate.statements[i].copy(), i) for i in range(0, len(gamestate.statements), 2)]},
                                     {'player': gameboard_context.p2_name, 'statements': [(gamestate.statements[i].copy(), i) for i in range(1, len(gamestate.statements), 2)]}]
        
        # pregenerate vote ui string bc it's too annoying in template. argument for jinja.
        gameboard_context.increased_cap = 1 if gamestate.meta.round == 11 else 0
        for data in gameboard_context.columns:
            for statement, i in data['statements']:
                logging.warning(statement)
                for votekey, votelist in list(statement.votes.items()):
                    vlist = votelist.copy()
                    statement['votes'][votekey + "_past"] = '<br>'.join(["⬤"*x + "◯" * ((i//2+1+(1 if x == 3 else 0)) - x) for x in map(int,vlist)])
                statement['empty'] = "◯" * (i//2 + 1 + gameboard_context.increased_cap)
        if round in ('CLARIFY', 'ADJUDICATE'):
            for col in gameboard_context.columns:
                col['extra_column'] = round
        if gamestate.meta.round > ROUND_STRUCTURE.index('REVEAL'):
            logging.warn(f'revealed: {gamestate.revealed}')
            gameboard_context.columns[0]['revealed'] = gamestate.revealed[0]
            gameboard_context.columns[1]['revealed'] = gamestate.revealed[1]

        gameboard_context.to_revise = gamestate.p1.to_revise if 'p1' in gamestate else gamestate.p2.to_revise
        if gameboard_context.to_revise is None: gameboard_context.to_revise = ''

        return gameboard_context
        
    # could be a classmethod
    def gameboard_data(self, game):
        return {'fps': game.options.get('fps', self.DEFAULT_OPTIONS['fps'])}
