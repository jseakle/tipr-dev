from tipr.utils import *

class Badge(object):
    def __init__(self, arg, round):
        self.arg = arg
        self.round = round

    def json(self):
        return [self.__class__.__name__, self.arg, self.round]

class DmgMultiplier(Badge):
    types = 'damage'

    def apply(self, gamestate, delta):
        for seat in seats:
            if seat in delta:
                if 'hp' in delta.get(seat):
                    damage(delta, seat, 2, mul=True)
                    total = combine_numeric_modifiers(delta.get(seat).hp)
                    add_message(delta, f"{seat}: DmgMultiplier({self.arg}) applies. {-total}")


effect_params = ['gamestate', 'history', 'seat', 'player', 'other', 'timing_bonus', 'level', 'badges_apply', 'delta']
class RPSCard(object):

    decks = ['basic']

    # called on every subclass
    def init(cls):
        # card stages count down; 0 means we're done and won't call apply again
        cls.abilities = update(Box({
            1: cls.level_up,
            2: cls.level_damage,
        }), {3+i:getattr(cls, x) for i, x in enumerate(reversed(cls.ability_order))})
        cls.abilities[len(cls.ability_order)+3] = cls.start

    @classmethod
    def get_badges(cls, player, type):
        badges = map(lambda name, args, round: next(filter(lambda c: c.__name__ == name, Badge.__subclasses__()))(args, round), *mzip(*player.badges))
        return filter(lambda badge: type in badge.types, badges)

    @classmethod
    def apply(cls, gamestate, history, seat):
        selection = gamestate.get(seat).selection
        ability_number = selection.ability_number
        timing_bonus = selection.timing
        player = gamestate.get(seat)
        level = player.cards.get(selection.name).level
        other = gamestate.get(opp(seat))
        delta = update(empty_delta(), Box({seat: {'selection': {'ability_number': ability_number - 1}}}))
        badges_apply = gamestate.meta.outcome.type == 'win' and gamestate.meta.outcome.player == seat
        globals().update(locals())
        badge_tuple = cls.abilities[ability_number](cls)
        # one-type abilities can be named after their type instead of returning it
        badge_types = list(badge_tuple or (cls.abilities[ability_number].__name__,))

        badges_used = []
        if badges_apply:
            for badge_type in badge_types:
                for badge in cls.get_badges(player, badge_type):
                    if badge.apply(gamestate, delta) != 'skip':
                        badges_used.append(badge.json())
        # the same badge can apply to two abilities of one card, so a set avoids duplication
        delta.get(seat).badges_used = unluple(luple(gamestate.get(seat).badges_used) | luple(badges_used))

        if 'damage' in badge_types and other.shields > 0:
            delta.ga(opp(seat)).shields = other.shields - 1
            add_message(delta, f"{opp(seat)}: Shield prevented {-combine_numeric_modifiers(delta.ga(opp(seat)).get('hp'))} dmg")
            update(delta, {opp(seat): {'hp': (('mul', 0),)}})

        # only use up badges after they've had a chance to apply to each stage
        if ability_number == 1:
            delta.ga(seat).badges = unluple(luple(gamestate.get(seat).badges.to_list()) -
                                            luple(gamestate.get(seat).badges_used.to_list()))
            delta.ga(seat).badges_used = []

        return delta

    def start(cls):
        return 'start'

    def level_up(cls):
        if badges_apply:
            cardname = gamestate.get(seat).selection.name
            card = gamestate.get(seat).cards.get(cardname)
            card.level += 1
            card.cracked = False
            update(delta, {seat: {'cards': {cardname: card}}})
            add_message(delta, f'{seat}: {cardname} levels up')
            return 'level_up'

    def level_damage(cls):
        if badges_apply:
            cardname = other.selection.name
            card = other.cards.get(cardname)

            if card.cracked:
                card.level=max(0, card.level - 1)
                card.cracked=False
                add_message(delta, f'{opp(seat)}: {cardname} levels down')
            else:
                card.cracked = True
                add_message(delta, f'{opp(seat)}: {cardname} cracks')
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
            update(delta, {seat: {'selection': {'ability_number': (('add', -1),)}}})
        damage(delta, opp(seat), dmg)
        add_message(delta, f"{seat}: Pebble hits! {dmg}")

    def badge(cls):
        update(delta, {seat: {'badges': {'dins': ['DmgMultiplier', 2, gamestate.meta.round]}}})
        add_message(delta, f"{seat}: Pebble grants DmgMultiplier(2x)")


class Napkin(RPSCard):

    type = PAPER
    ability_order = ['health', 'damage', 'shield']

    def health(cls):
        damage(delta, seat, -level)
        add_message(delta, f"{seat}: Napkin heals! {level}")

    def damage(cls):
        other_ability = other.selection.name
        other_level = other.cards.get(other_ability).level
        damage(delta, opp(seat), other_level)
        add_message(delta, f"{seat}: Napkin hits! {other_level}")

    def shield(cls):
        update(delta, {seat: {'shields': (('add', 1),)}})
        add_message(delta, f"{seat}: Napkin grants a shield")


class Truce(RPSCard):

    type = DEFAULT
    ability_order = ['loss']

    def loss(cls):
        damage(delta, seat, 1)


class PaciveIncome(RPSCard):

    type = DEFAULT
    ability_order = ['health']

    def health(cls):
        damage(delta, seat, -2)

for cls in RPSCard.__subclasses__():
    RPSCard.init(cls)