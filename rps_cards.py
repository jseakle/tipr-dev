from tipr.utils import *

effect_params = ['gamestate', 'history', 'seat', 'player', 'other', 'timing_bonus', 'level', 'badges_apply', 'delta', 'badges_used']
class RPSCard(object):

    # called on every subclass
    def init(cls):
        # card stages count down; 0 means we're done and won't call apply again
        cls.abilities = update(Box({
            1: cls.level_up,
            2: cls.level_damage,
        }), {3+i:x for i, x in enumerate(reversed(cls.ability_order))})

    @classmethod
    def get_badges(cls, player, type):
        badges = map(lambda name, args: next(filter(lambda c: c.name == name, Badge.__subclasses__()))(args), player.badges)
        return filter(lambda badge: type in badge.types, badges)

    @classmethod
    def apply(cls, gamestate, history, seat):
        selection = gamestate.get(seat).selection
        ability = selection.ability
        timing_bonus = selection.timing
        player = gamestate.get(seat)
        level = player.cards.get(ability).level
        other = gamestate.get(opp(seat))
        delta = Box({seat: {'selection': {'ability': ability - 1}}})

        badges_apply = gamestate.meta.outcome.type == 'win' and gamestate.meta.outcome.player == seat
        # possibly _the_ most cursed line of code i've ever written
        inject(**{param: locals()[param] for param in effect_params})(cls.stages[ability])
        badge_types = list(cls.abilities[ability]())
        badges_used = []
        for badge_type in badge_types:
            for badge in cls.get_badges(player, badge_type):
                if badge.apply(gamestate, delta):
                    badges_used.append(badge)
        delta.get(seat).badges_used = list(set(gamestate.get(seat).badges_used + badges_used))

        if ability == 1:
            delta.ga(seat).badges = list(set(gamestate.get(seat).badges) - set(badges_used))
            delta.ga(seat).badges_used = []

        return delta

    @classmethod
    def level_up(cls):
        if badges_apply:
            cardname = gamestate.get(seat).selection.name
            card = gamestate.get(seat).cards.get(cardname)
            card.level += 1
            card.cracked = False
            update(delta, {seat: {'cards': {cardname: card}}})
            delta.meta.message = f'{cardname} levels up'
            return 'level_up'


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
            update(delta, {opp(seat): {'cards': {cardname: card}}})
            return 'level_damage'


class Pebble(RPSCard):

    type = ROCK
    ability_order = []

    def damage(cls):
        dmg = 15
        if timing_bonus == 2:
            dmg += 3 * level
        update(delta, {opp(seat): {'hp': ('add', -dmg)}})
        return 'damage'

    def badge(cls):
        update(delta, {seat: {'badges': {'ins': {'dmg_multiplier': 2}}}})

for cls in RPSCard.__subclasses__():
    RPSCard.init(cls)
    for name in cls.__dict__:
        item = getattr(cls, name)
        if callable(item):
            setattr(cls, item, classmethod(item))
