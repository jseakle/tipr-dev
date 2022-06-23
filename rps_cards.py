from tipr.utils import *

class Badge(object):
    def __init__(self, arg):
        self.arg = arg

class DmgMultiplier(Badge):
    types = 'damage'

    def apply(self, gamestate, delta):
        for seat in seats:
            if seat in delta:
                if 'hp' in delta.get(seat):
                    update(delta, {seat: {'hp': ('mul', 2)}})
                    total = combine_numeric_modifiers(delta.get(seat).hp)
                    add_message(delta, f"DmgMultiplier({self.arg}) applies. {total}")


effect_params = ['gamestate', 'history', 'seat', 'player', 'other', 'timing_bonus', 'level', 'badges_apply', 'delta', 'badges_used']
class RPSCard(object):

    # called on every subclass
    def init(cls):
        # card stages count down; 0 means we're done and won't call apply again
        cls.abilities = update(Box({
            1: cls.level_up,
            2: cls.level_damage,
        }), {3+i:x for i, x in enumerate(reversed(cls.ability_order))})
        cls.abilities[i+1] = cls.start

    @classmethod
    def get_badges(cls, player, type):
        badges = map(lambda name, args: next(filter(lambda c: c.__name__ == name, Badge.__subclasses__()))(args), *mzip(*player.badges))
        return filter(lambda badge: type in badge.types, badges)

    @classmethod
    def apply(cls, gamestate, history, seat):
        selection = gamestate.get(seat).selection
        ability = selection.ability
        timing_bonus = selection.timing
        player = gamestate.get(seat)
        level = player.cards.get(ability).level
        other = gamestate.get(opp(seat))
        delta = Box({seat: {'selection': {'ability_number': ability - 1}}})

        badges_apply = gamestate.meta.outcome.type == 'win' and gamestate.meta.outcome.player == seat
        # possibly _the_ most cursed line of code i've ever written
        inject(**{param: locals()[param] for param in effect_params})(cls.stages[ability])
        # one-type abilities can be named after their type instead of returning it
        badge_types = list(cls.abilities[ability]() or cls.abilities[ability].__name__)
        badges_used = []
        for badge_type in badge_types:
            for badge in cls.get_badges(player, badge_type):
                if badge.apply(gamestate, delta):
                    badges_used.append(badge)
        delta.get(seat).badges_used = list(set(gamestate.get(seat).badges_used + badges_used))

        if 'damage' in badge_types and other.shields > 0:
            delta.ga(opp(seat)).shields = other.shields - 1
            update(delta, {opp(seat): {'hp': ('mul', 0)}})
            add_message(delta, "Shield used")

        # only use up badges after they've had a chance to apply to each stage
        if ability == 1:
            delta.ga(seat).badges = list(set(gamestate.get(seat).badges) - set(badges_used))
            delta.ga(seat).badges_used = []

        return delta

    @classmethod
    def start(cls):
        return 'start'

    @classmethod
    def level_up(cls):
        if badges_apply:
            cardname = gamestate.get(seat).selection.name
            card = gamestate.get(seat).cards.get(cardname)
            card.level += 1
            card.cracked = False
            update(delta, {seat: {'cards': {cardname: card}}})
            add_message(delta, f'{cardname} levels up')
            return 'level_up'


    @classmethod
    def level_damage(cls):
        if badges_apply:
            cardname = other.selection.name
            card = other.cards.get(cardname)

            if card.cracked:
                card.level=max(0, card.level - 1)
                card.cracked=False
                add_message(delta, f'{cardname} levels down')
            else:
                card.cracked = True
                add_message(delta, f'{cardname} cracks')
            update(delta, {opp(seat): {'cards': {cardname: card}}})
            return 'level_damage'


class Pebble(RPSCard):

    type = ROCK
    ability_order = ['damage', 'badge']

    def damage(cls):
        dmg = 15
        if timing_bonus == 2:
            dmg += 3 * level
        if timing_bonus == 0:
            update(delta, {seat: {'selection': {'ability_number': ('add', -1)}}})
        update(delta, {opp(seat): {'hp': ('add', -dmg)}})
        add_message(delta, f"Pebble hits! {dmg}")

    def badge(cls):
        update(delta, {seat: {'badges': {'ins': ['DmgMultiplier', 2]}}})
        add_message(delta, "Pebble grants DmgMultiplier(2x)")


class Napkin(RPSCard):

    type = PAPER
    ability_order = ['health', 'damage', 'shield']

    def health(cls):
        update(delta, {seat: {'hp': ('add', level)}})
        add_message(delta, f"Napkin heals! {level}")

    def damage(cls):
        other_ability = other.selection.name
        other_level = other.cards.get(other_ability).level
        update(delta, {opp(seat): {'hp': ('add', -other_level)}})
        add_message(delta, f"Napkin hits! {other.level}")

    def shield(cls):
        update(delta, {seat: {'shields': {'add', 1}}})
        add_message(delta, "Napkin grants a shield")




for cls in RPSCard.__subclasses__():
    RPSCard.init(cls)
    for name in cls.__dict__:
        item = getattr(cls, name)
        if callable(item):
            setattr(cls, item, classmethod(item))
