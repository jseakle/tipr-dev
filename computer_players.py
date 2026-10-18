class ComputerPlayer:
    """A stateless computer player.

    It sits in a seat under its own (reserved) name and knows only what a human in that
    seat could see: the seat's view of the game and the game's history. The server asks it
    for moves while handling a seated human's request, so it never acts on its own.
    """

    name = ''

    def moves(self, rules, view, history, seat):
        """Return the moves to submit now for seat index `seat`, in order (possibly none)."""
        raise NotImplementedError
