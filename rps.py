import functools
import random
from box import Box
from utils import *


class Card(object):
    def __init__(self, card):
        self.name = card.name
        self.type = card.type
        self.level = 1
        self.cracked = False

    def take_damage(self, amt):
        if self.cracked:
            self.level = max(0, self.level-1)
        else:
            self.cracked = True
            
    def level_up(self):
        self.cracked = False
        self.level += 1

    def


class RPSRules(object):

    STATIC_OPTIONS = {'player_count': 2,
                      'deck': 'basic'}

    def player_state(self, options):
        STARTING_HP = 250
        MAX_HP = STARTING_HP / .75
        return {
                'max_hp': MAX_HP,
                'hp': STARTING_HP,
                'coins': 0,
                'badges': [],
                'effects': [],
                'stages': {1: [], 2: [], 3: []},
                'cards': {card.name: {'level': 1, 'cracked': False} for card in self.deck(options)}
            }

    def start_state(self, options):
        starting_state = Box({
            'meta': {
                'round': 1,
                'stage': 1,
            },
            'p1': self.player_state(options),
            'p2': self.player_state(options),
        })
        return starting_state

    @functools.cache
    def deck(self, deck, names_only=False):
        card_classes = RPSCard.__subclasses__.filter(lambda cls: deck in cls.decks)
        if names_only:
            return list(card_classes.keys())
        return {card.name: card for card in card_classes }

    def get_selections(self, options, gamestate):
        ret = []
        for seat in ('p1', 'p2'):
            found = False
            for stage in (1, 2, 3):
                for action in gamestate[seat].stages[stage]:
                    if action.kind is 'RPS':
                        found = True
                        ret.append(Box(seat=seat, stage=stage, card=self.deck(options.deck)[action.name]))  # modifiers go in here too
                        break
                if found:
                    break
            if not found:
                ret.append(None)
        return ret

    def response(self, game, seat):
        return self.pure_response(Box(game.options), Box(game.gamestate), game.history, seat)

    def pure_response(self, options, gamestate, history, seat):
        match gamestate.meta.stage, history:
            case _, []:
                return gamestate.update({'deck': self.deck(options.deck, names_only=True)})
            case stage, [*_, last] if stage < 4:
                # this player's current view + other player's view at last keyframe
                return {k: v for k, v in gamestate if k is not ('p1', 'p2')[seat]}\
                    .update(last[0][('p2', 'p1')[seat]])

        return gamestate

    def do_update(self, game):
        return self.pure_update(Box(game.options), Box(game.gamestate), game.history)

    def pure_update(self, options, gamestate, history):
        match gamestate.meta.stage:
            case 1 | 2:
                gamestate.meta.stage += 1
            case 3:
                # Box(seat, stage, card)
                p1_rps, p2_rps = self.get_selections(options, gamestate)
                happens_first = happens_second = Box(owner=None, rps=None, level=0, timing=None)
                message = 'Message missing'
                match p1_rps, p2_rps:
                    case None, None:
                        happens_first.update(owner='p1', rps=Truce)
                        happens_second.update(owner='p2', rps=Truce)
                    case ({'seat': w}, None) | (None, {'seat': w}):
                        happens_first.update(owner='p2' if w.seat is 'p1' else 'p1', rps=PaciveIncome)
                        happens_second.update(owner=w.seat, rps=w.card, 
                                              level=gamestate[w.seat].cards[w.card.name].level)
                    case Box() as p1, Box() as p2 if p1_rps.card.type == p2_rps.card.type:
                        match p1_rps.stage, p2_rps.stage:
                            case x, y if x == y:
                                order = [p1, p2]
                                if gamestate.p1.hp == gamestate.p2.hp and gamestate.p1.coins == gamestate.p2.coins:
                                    random.shuffle(order)
                                elif gamestate.p1.hp == gamestate.p2.hp:
                                    order.sort(key=lambda box: gamestate[box.seat].coins, reverse=True)
                                else:
                                    order.sort(key=lambda box: gamestate[box.seat].hp, reverse=True)
                                happens_first.update(owner=order[0].seat, rps=order[0].card,
                                                     level=gamestate[order[0].seat].cards[order[0].card.name].level)
                                happens_second.update(owner=order[1].seat, rps=order[1].card,
                                                      level=gamestate[order[1].seat].cards[order[1].card.name].level)
                            case x, y:
                                winner, loser = (p1, p2) if x < y else (p2, p1)
                                happens_first.update(owner=winner.seat, rps=winner.card,
                                                     level=gamestate[winner.seat].cards[winner.card.name].level / 2,
                                                     timing=1 if abs(x-y) == 2 else None)
                    case Box() as p1, Box() as p2:
                        winner, loser = (p1, p2) if (p2.card.type + 1) % 3 == p1.card.type else (p2, p1)
                        wincard = gamestate[winner.seat].cards[winner.card.name]
                        happens_first.update(owner=winner.seat, rps=winner.card, level=wincard.level,
                                             timing=max(0, winner.stage - loser.stage))
                        wincard.level_up()
                        gamestate[loser.seat].cards[loser.card.name]



