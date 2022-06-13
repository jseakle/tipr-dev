from tipr.utils import *

effect_params = ['gamestate', 'history', 'resolving_player', 'other', 'timing_bonus', 'level', 'badges_apply', 'delta', 'badges_used']
class RPSCard(object):

    # called on every subclass
    def init(cls):
        # card stages count down; 0 means we're done and won't call apply again
        cls.abilities = update(Box({
            1: cls.level_up,
            2: cls.level_damage,
        }), {3+i:x for i, x in enumerate(reversed(cls.ability_order))})

    @classmethod
    def apply(cls, gamestate, history, resolving_player):
        selection = gamestate.get(resolving_player).selection
        ability = selection.ability
        timing_bonus = selection.timing
        level = gamestate.get(resolving_player).cards.get(ability).level
        other = gamestate.get(opp(resolving_player))
        delta = Box({resolving_player: {'selection': {'ability': ability - 1}}})

        badges_apply = gamestate.meta.outcome.type == 'win' and gamestate.meta.outcome.player == resolving_player
        badges_used = []
        # possibly _the_ most cursed line of code i've ever written
        inject(**{param: locals()[param] for param in effect_params})(cls.stages[ability])
        cls.abilities[ability]()
        delta.get(resolving_player).badges_used = list(set(gamestate.get(resolving_player).badges_used + badges_used))

        if ability == 1:
            delta.ga(resolving_player).badges = list(set(gamestate.get(resolving_player).badges) - set(badges_used))
            delta.ga(resolving_player).badges_used = []

        return delta

    @classmethod
    def level_up(cls):
        if badges_apply:
            cardname = gamestate.get(resolving_player).selection.name
            card = gamestate.get(resolving_player).cards.get(cardname)
            card.level += 1
            card.cracked = False
            update(delta, {resolving_player: {'cards': {cardname: card}}})
            delta.meta.message = f'{cardname} levels up'
            for badge in cls.get_badges(gamestate, 'level_up'):
                if badge.apply(gamestate, delta):
                    badges_used.append(badge)

    @classmethod
    def level_damage(cls):
        if badges_apply:
            cardname = other.selection.name
            card = other.cards.get(cardname)

            if card.cracked:
                card.level=max(0, card.level - 1)
                card.cracked=False
                delta.meta.message = f'{cardname} levels down'
            else:
                card.cracked = True
                delta.meta.message = f'{cardname} cracks'
            update(delta, {other: {'cards': {cardname: card}}})
            for badge in cls.get_badges(gamestate, 'level_damage'):
                if badge.apply(gamestate, delta):
                    badges_used.append(badge)


class Pebble(RPSCard):

    type = ROCK
    ability_order = []

    def damage(cls):
        dmg = 15
        if timing_bonus == 2:
            dmg += 3 * level
        update(delta, {other: {'hp': gamestate.get(other).hp - dmg}})
        for badge in cls.get_badges(gamestate, 'damage'):
            if badge.apply(gamestate, delta):
                badges_used.append(badge)

for cls in RPSCard.__subclasses__():
    RPSCard.init(cls)
    for name in cls.__dict__:
        item = getattr(cls, name)
        if callable(item):
            setattr(cls, item, classmethod(item))
