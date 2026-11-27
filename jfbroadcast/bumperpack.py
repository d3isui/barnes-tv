"""Built-in bumper packs: deadpan late-night text bumps (white words on black, lowercase).

Each pack is added once to every install (new and existing). Deleted ones stay deleted; the Bumpers page can bring
them back. "when" limits a bumper to a time of day or to the current weather (from the weather channel).
"""

PACK_ID = "snark-1"


def _b(bid, name, kind, cards, when=""):
    return {"id": f"pk1-{bid}", "name": name, "kind": kind, "when": when, "pack": PACK_ID,
            "cards": [{"text": t, "seconds": s} for t, s in cards]}


SNARK = [
    # ---- going into a break
    _b("into-01", "They never leave", "into_break", [
        ("{show} will be right back.", 2.5), ("so will these commercials.", 2.5), ("they always come back.", 3)]),
    _b("into-02", "Stretch", "into_break", [
        ("quick break.", 2), ("stand up.", 1.8), ("stretch.", 1.8), ("sit back down.", 2),
        ("you weren't going anywhere. we can tell.", 3.5)]),
    _b("into-03", "Two minutes", "into_break", [
        ("you have about two minutes.", 2.8), ("we're not saying what for.", 2.5), ("but you know.", 2.5)]),
    _b("into-04", "Paid for this", "into_break", [
        ("the following messages paid for all of this.", 3.2), ("we didn't ask questions.", 2.5),
        ("neither should you.", 2.5)]),
    _b("into-05", "Mute button", "into_break", [
        ("break time.", 2), ("your remote has a mute button.", 2.8),
        ("we're not allowed to tell you to use it.", 3), ("so we didn't.", 2.5)]),
    _b("into-06", "Breather", "into_break", [
        ("{show} needs a minute.", 2.5), ("it's been through a lot.", 2.5), ("haven't we all.", 2.5)]),
    _b("into-07", "Ads ahead", "into_break", [
        ("ads ahead.", 2), ("some of them are older than you.", 3), ("respect your elders.", 2.8)]),

    # ---- coming back
    _b("out-01", "We missed you", "out_of_break", [
        ("welcome back.", 2), ("we missed you.", 2.2), ("that's not true. we're a television channel.", 3.5),
        ("anyway. {show}.", 2.5)]),
    _b("out-02", "You stayed", "out_of_break", [
        ("and we're back.", 2), ("you didn't change the channel.", 2.6), ("we noticed.", 2),
        ("here's {show}.", 2.5)]),
    _b("out-03", "Survived", "out_of_break", [
        ("okay. the commercials are over.", 2.8), ("you survived.", 2.2), ("{show} resumes now.", 2.5)]),
    _b("out-04", "Kitchen", "out_of_break", [
        ("back to {show}.", 2.2), ("if you missed what happened,", 2.5),
        ("so did we. we were in the kitchen.", 3.2)]),
    _b("out-05", "Where were we", "out_of_break", [
        ("where were we.", 2.2), ("right.", 1.6), ("{show}.", 2.5)]),

    # ---- before the next show
    _b("next-01", "We've seen it", "next", [
        ("coming up next:", 2), ("{next}.", 2.8), ("we've seen it. it's fine.", 2.6), ("you'll like it.", 2.4)]),
    _b("next-02", "Find the remote", "next", [
        ("next up is {next}.", 2.8), ("it starts at {next_time}.", 2.5),
        ("that's enough time to find the remote.", 3), ("go.", 1.8)]),
    _b("next-03", "Stay put", "next", [
        ("that was {show}.", 2.5), ("this is still {channel}.", 2.5), ("next: {next}.", 2.8), ("stay put.", 2)]),
    _b("next-04", "Long sentence", "next", [
        ("{next} is next.", 2.8), ("we spent a long time on that sentence.", 3)]),
    _b("next-05", "Not your parents", "next", [
        ("you could go to bed.", 2.4), ("or you could watch {next}.", 2.8), ("we're not your parents.", 2.5),
        ("{next}. {next_time}.", 2.8)]),
    _b("next-06", "Out loud", "next", [
        ("next: {next}.", 2.6), ("you were going to watch it anyway.", 2.8),
        ("we're just saying it out loud.", 2.8)]),

    # ---- anywhere
    _b("any-01", "Channel number", "any", [
        ("this is {channel}.", 2.4), ("channel {number}.", 2), ("you're welcome.", 2.4)]),
    _b("any-02", "Ratings", "any", [
        ("we don't have ratings.", 2.4), ("we have you.", 2), ("that's worse, somehow.", 2.6)]),
    _b("any-03", "This is a bump", "any", [
        ("hello.", 1.6), ("this is a bump.", 2.2), ("you're watching one right now.", 2.6),
        ("it's almost over.", 2.2), ("there.", 1.6)]),
    _b("any-04", "Someone is reading this", "any", [
        ("somebody is reading this.", 2.6), ("it's you.", 2), ("hi.", 1.8)]),
    _b("any-05", "Something profound", "any", [
        ("we were going to put something profound here.", 3.4), ("then we didn't.", 2.4)]),
    _b("any-06", "Fun fact", "any", [
        ("fun fact:", 1.8), ("this sentence is on your television.", 2.8), ("that's the whole fact.", 2.4)]),
    _b("any-07", "Water", "any", [
        ("reminder:", 1.8), ("drink some water.", 2.2), ("not because of anything we said.", 2.6),
        ("just in general.", 2.2)]),
    _b("any-08", "Couch dent", "any", [
        ("your couch has a dent in it now.", 2.6), ("it's shaped like you.", 2.2), ("we think that's beautiful.", 2.6)]),
    _b("any-09", "Blink", "any", [
        ("hey.", 1.6), ("you've been staring at this for a while.", 3), ("blink.", 1.8)]),
    _b("any-10", "Nobody answered", "any", [
        ("we asked our viewers what they wanted.", 3), ("nobody answered.", 2.2), ("so here's more television.", 2.6)]),
    _b("any-11", "Probably", "any", [
        ("it's {day}.", 2), ("probably.", 1.8), ("we don't really check.", 2.4)]),
    _b("any-12", "Out loud", "any", [
        ("if you're reading this out loud,", 2.6), ("please stop.", 2), ("people are trying to watch.", 2.6)]),
    _b("any-13", "In the couch", "any", [
        ("there's no remote for real life.", 2.6), ("there is one for this tv, though.", 2.6),
        ("it's in the couch.", 2.4)]),
    _b("any-14", "Programming", "any", [
        ("our programming department", 2.4), ("is one computer", 2), ("and it's doing its best.", 2.6)]),
    _b("any-15", "No skip", "any", [
        ("there's no skip button.", 2.4), ("this is television.", 2.2), ("we used to live like this.", 2.6)]),
    _b("any-16", "Don't touch that dial", "any", [
        ("don't touch that dial.", 2.4), ("you don't have a dial.", 2.2), ("don't touch anything.", 2.4)]),
    _b("any-17", "Background noise", "any", [
        ("if this is just background noise for you,", 3), ("that's okay.", 2), ("we're good at it.", 2.4)]),

    # ---- time of day
    _b("late-01", "One more episode", "any", [
        ("it's {time}.", 2.2), ("you said \"one more episode\"", 2.6), ("two episodes ago.", 2.2),
        ("we won't tell anyone.", 2.4)], "late_night"),
    _b("late-02", "In this together", "any", [
        ("hey. it's late.", 2.2), ("you're still up.", 2), ("so are we.", 2), ("we're in this together now.", 2.6)],
       "late_night"),
    _b("late-03", "Good part of the night", "any", [
        ("it's {time}.", 2.2), ("everyone else is asleep.", 2.4), ("this is the good part of the night.", 2.8)],
       "late_night"),
    _b("late-04", "The sun", "any", [
        ("the sun comes up in a few hours.", 2.6), ("it doesn't need to know about this.", 2.8)], "late_night"),
    _b("morn-01", "Good morning", "any", [
        ("good morning.", 2), ("or as we call it,", 2.2), ("the part of the day after the good part.", 3)], "morning"),
    _b("morn-02", "Solid choice", "any", [
        ("it's {time} in the morning", 2.4), ("and you chose television.", 2.4), ("solid choice.", 2.2)], "morning"),
    _b("wknd-01", "Nowhere to be", "any", [
        ("it's {day}.", 2), ("you don't have to be anywhere.", 2.6), ("so be here.", 2.2)], "weekend"),

    # ---- weather (needs a weather channel; skipped automatically when there isn't one)
    _b("wx-01", "There's a window", "any", [
        ("it's {weather} in {city}.", 2.8), ("we checked.", 2), ("you could too. there's a window right there.", 3.2)]),
    _b("wx-02", "Like a reasonable person", "any", [
        ("it's raining in {city}.", 2.6), ("good thing you're inside.", 2.4), ("watching us.", 2),
        ("like a reasonable person.", 2.4)], "rain"),
    _b("wx-03", "Pick one", "any", [
        ("it's {temp} outside.", 2.4), ("inside, it's {channel}.", 2.4), ("pick one.", 2)], "cold"),
    _b("wx-04", "Invented for this", "any", [
        ("it's {temp} out there.", 2.4), ("air conditioning was invented for exactly this.", 3.2),
        ("so was television.", 2.4)], "hot"),
    _b("wx-05", "Very loud", "any", [
        ("it's snowing.", 2.2), ("everything is quiet.", 2.2), ("except this tv.", 2), ("sorry.", 1.8)], "snow"),
    _b("wx-06", "Perfect weather", "any", [
        ("it's {weather} outside.", 2.6), ("perfect weather.", 2.2), ("for staying in.", 2.2), ("obviously.", 2)],
       "nice"),
    _b("wx-07", "It's outside", "any", [
        ("there's a thunderstorm out there.", 2.6), ("it can't get you.", 2.2), ("it's outside.", 2),
        ("details on channel {weather_number}.", 2.6)], "storm"),
    _b("wx-08", "Plan accordingly", "any", [
        ("tomorrow: {tomorrow}.", 2.6), ("high of {tomorrow_high}.", 2.2), ("tonight: this.", 2.2),
        ("plan accordingly.", 2.2)]),
    _b("wx-09", "Hold on to something", "any", [
        ("it's windy out.", 2.2), ("{wind}, apparently.", 2.2), ("hold on to something.", 2.2),
        ("like the remote.", 2.2)], "windy"),
    _b("wx-10", "That's the whole show", "any", [
        ("the weather is on channel {weather_number}.", 2.8), ("it's {temp} right now.", 2.4),
        ("that's the whole show.", 2.2), ("it's great.", 2)]),
    _b("wx-11", "Can't see anything", "any", [
        ("it's foggy in {city}.", 2.4), ("you can't see anything out there.", 2.6), ("you can see this, though.", 2.4)],
       "fog"),
    _b("wx-12", "That's a threat", "any", [
        ("{temp}.", 2), ("that's not a temperature.", 2.4), ("that's a threat.", 2.2), ("stay in.", 2)], "freezing"),
    _b("wx-13", "Sunset", "any", [
        ("the sun sets at {sunset}.", 2.6), ("we'll still be here.", 2.4)]),
    _b("wx-14", "Feels like", "any", [
        ("it's {temp}.", 2), ("it feels like {feels_like}.", 2.4), ("we feel like television.", 2.4)]),
    _b("wx-15", "Rain chance", "into_break", [
        ("{rain_chance} chance of rain today.", 2.6), ("100% chance of commercials.", 2.4),
        ("right now, actually.", 2.2)]),
]

PACKS = {PACK_ID: SNARK}
