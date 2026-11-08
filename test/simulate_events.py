"""Offline model of World's game event logic, no game needed: plugin/src/Personal.cpp (every sink, the 1 s poll with
the fight tracking, rescue windows, rate limits, ResetFight) and the Papyrus side that receives its events
(Source/Scripts/MLWW_Personal.psc handlers, trade totals, QueueFacts batching, Line(); MLWW_Facts.psc; MLWW_State.psc
CheckDungeons). Every model function names the source lines it mirrors.

Random event streams drive it: big fights with many enemies, summons on every side, followers going down, getting up and
dying, single, area and over-time heals, area damage, fast travel, save / load / new game mid-fight, two saves
alternating, barter sessions buying and selling, the gift menu and other gifts, bribes, pickpocketing and theft.

Checked after every event:
  attribution  every event names the actor who really did it, in the save that is loaded now
  rate         Struck 60 s, FriendlyFire 10 s, Healed 60 s per NPC and direction
  leak         nothing from before a load or a new game reaches the fight state or Papyrus after it
  counts       every stored number stays >= 0 (days and "none" markers -1) and below 2^31
  work         operations per event, worst case printed; must stay under a fixed bound
  batching     every NPC queued for a fact write is written within FACT_DELAY
  join         after an NPC joins a conversation, their fact file holds exactly what this save's numbers say
  line         Line() never needs more than its 8 slots

The streams also cover follower inventory windows (gold given and taken back), murders, sneaking up on sleepers
and followers told to wait.

The same streams also run against the logic as it was before the 2026-11-06 and 2026-11-08 fixes (--original). A normal run does
both: the fixed logic must be clean, and every old defect must show up in the original, so the model is known to see it.

usage: py -3 test/simulate_events.py [--seeds N] [--steps N] [--original] [-v]
"""
import argparse
import copy
import random
import sys
from collections import defaultdict, deque

# Personal.cpp:26-38
CRIME_POLL, CAUGHT, HIT_REPEAT, RECHECK, HEALTH_READ = 1.0, 3.0, 60.0, 0.5, 2.0
HEAL_REPEAT, FRIENDLY_REPEAT, RESCUE, DEFEND, MIN_FIGHT, FIGHT_QUIET = 60.0, 10.0, 15.0, 5.0, 5.0, 5.0
LOW_HEALTH, PARTY_RANGE = 0.25, 8192.0
FACT_DELAY = 30.0  # MLWW_Personal.psc:33
DUNGEON_WAIT = 5.0  # MLWW_State.psc:49
INT_MAX = 2 ** 31 - 1
PLAYER = 0x14
FRAME = 1 / 30

# What changed on 2026-11-06; --original turns all of them off.
FIXES = {
    'epoch': 'tasks and delayed rechecks queued before a load or new game are dropped (Personal.cpp:90-101, 557-559, 637-638)',
    'reset_all': 'ResetFight also forgets the bounty total, take/pickpocket/barter windows and rate limits (785-805)',
    'pickpocket_close': 'only closing the pickpocket menu itself starts the caught window (Personal.cpp:325)',
    'take_after_pickpocket': 'an owned take after the pickpocket menu closed is the newer crime (Personal.cpp:147)',
    'summon_side': 'a summon of the player or a member is not an attacker of the party (Personal.cpp:546-548, 561)',
    'other_hit_guard': 'friendly fire is not counted when someone else hit the same target around it (471-477, 512-520)',
    'dead_saved': 'no "saved" for a member who is dead (Personal.cpp:656)',
    'barter_take': 'goods bought in the barter menu are not a take (Personal.cpp:276-277, 301)',
    'bribe_to_nobody': 'the World bribe removes the gold instead of handing it to the guard (MLWW_Crime.psc:118)',
    # 2026-11-08
    'follower_gold_net': 'gold to a follower counts once, as the net when their inventory window closes (Personal.cpp OnMenu, OnMoved)',
    'struck_party': 'no "struck" for teammates and summons; they get friendly fire instead (Personal.cpp hit sink)',
    'murder_victim': 'the murder stamp comes only from a person who was no enemy, killed by the player (Personal.cpp OnDeath, MLWW_Personal.OnMurder)',
    'trade_both_ways': 'a barter menu reports the gold paid and the gold received, not only the balance (Personal.cpp OnMenu)',
    'waiting_not_party': 'a follower told to wait is not in the party (Personal.cpp IsMember)',
    'sneak_no_wake': 'activating a sleeper while sneaking is not waking them (Personal.cpp OnActivate)',
}

# Which old defect a violation category belongs to (for the self test).
BUG_OF = {
    'leak_task': 'epoch', 'wrong_save': 'epoch', 'crime_across_load': 'reset_all',
    'caught_wrong_owner': 'pickpocket_close', 'caught_newer_take': 'take_after_pickpocket',
    'defended_summon': 'summon_side', 'friendly_fire_not_theirs': 'other_hit_guard', 'saved_dead': 'dead_saved',
    'caught_purchase': 'barter_take', 'gift_is_payment': 'bribe_to_nobody',
    'gift_taken_back': 'follower_gold_net', 'struck_teammate': 'struck_party', 'murder_of_enemy': 'murder_victim',
    'trade_net_only': 'trade_both_ways', 'waiting_credited': 'waiting_not_party', 'woken_while_sneaking': 'sneak_no_wake',
}

PEOPLE = ('Bandit', 'Bandit Chief', 'Necromancer', 'Vilkas')  # enemies who are people (ActorTypeNPC)


class Actor:
    def __init__(self, fid, kind, name, hp=100.0, **kw):
        self.fid, self.kind, self.name = fid, kind, name
        self.base = fid + 0x100000 if fid != PLAYER else 0x7
        self.maxhp = self.hp = hp
        self.teammate = kind == 'follower'
        self.commander = None
        self.dead = self.bleed = self.combat = self.sleeping = False
        self.hostile = kind == 'enemy'
        self.unique = self.dragon = False
        self.level, self.loaded, self.dist, self.merchant_chest = 10, True, 300.0, None
        self.waiting = self.assaulted = self.sneaking = False
        self.__dict__.update(kw)

    @property
    def npc(self):  # HasKeywordString("ActorTypeNPC")
        return self.kind in ('player', 'townsfolk', 'merchant', 'guard', 'follower') or (self.kind == 'enemy' and self.name in PEOPLE)


class World:
    """The game: actors, bounty, gold, menus. Snapshotted whole on save."""

    def __init__(self, rng, tl):
        self.tl, self.actors, self.next_fid = tl, {}, 0x100
        self.add(Actor(PLAYER, 'player', 'Player', 300.0))
        self.bounty, self.gold = 0.0, defaultdict(int)
        self.gold[PLAYER] = 2000
        self.menus, self.container_mode, self.menu_target = set(), None, None
        self.game_hours, self.stat_dungeons, self.location = 8.0, 0, 'Whiterun'
        for name in ('Lydia', 'Faendal', 'Serana')[:rng.randint(1, 3)]:
            self.add(Actor(self.fid(), 'follower', name, 250.0))
        for name in ('Belethor', 'Arcadia', 'Adrianne'):
            m = self.add(Actor(self.fid(), 'merchant', name, 80.0))
            chest = self.add(Actor(self.fid(), 'chest', name + ' chest', 1.0, owner=m.base if rng.random() < 0.6 else None))
            m.merchant_chest = chest.fid
            self.gold[chest.fid] = rng.choice((300, 750, 1500, 4000))
        for name in ('Hulda', 'Ysolda', 'Brenuin', 'Nazeem'):
            self.add(Actor(self.fid(), 'townsfolk', name, 60.0))
        self.add(Actor(self.fid(), 'guard', 'Whiterun Guard', 150.0))
        for owner in ('Hulda', 'Nazeem'):
            o = self.named(owner)
            self.add(Actor(self.fid(), 'chest', owner + "'s chest", 1.0, owner=o.base))

    def fid(self):
        self.next_fid += 1
        return self.next_fid

    def add(self, a):
        self.actors[a.fid] = a
        return a

    def named(self, name):
        return next(a for a in self.actors.values() if a.name == name)

    def of(self, kind, alive=True):
        return [a for a in self.actors.values() if a.kind == kind and (not alive or not a.dead)]

    @property
    def player(self):
        return self.actors[PLAYER]

    def day(self):
        return int(self.game_hours / 24)


# ---------------------------------------------------------------------------------------------------------------------
# The plugin (Personal.cpp)
# ---------------------------------------------------------------------------------------------------------------------

class Plugin:
    def __init__(self, sim, fixes):
        self.sim, self.fix = sim, fixes
        self.epoch = 0
        self.ops = 0
        self.crime_total = -1.0
        self.last_take = None  # (owner_base, kind, when)
        self.pp_target, self.pp_until = None, -1e9
        self.barter_target, self.barter_gold, self.barter_sold = None, 0, {}
        self.last_hit, self.repeat = {}, {}
        self.last_attacker, self.down, self.player_low = {}, {}, None
        self.player_attackers, self.health, self.party_hits = {}, {}, {}
        self.fighters, self.defenders = set(), set()
        self.in_fight, self.fight_start, self.last_combat = False, 0.0, 0.0
        self.trade_target, self.trade_gold, self.barter_spent, self.barter_earned = None, 0, 0, 0
        self.assaulted = set()

    # -- helpers -------------------------------------------------------------------------------------------------------
    @property
    def w(self):
        return self.sim.world

    def now(self):
        return self.sim.now

    def op(self, n=1):
        self.ops += n

    def get(self, fid):  # ActorHandle::get(): the reference in the game that is loaded now, or nothing
        self.op()
        return self.w.actors.get(fid) if fid is not None else None

    def send(self, name, text, num, sender):  # Personal.cpp:82-86
        self.sim.deliver(name, text, num, sender)

    def task(self, fn, label, epoch=None, gen=None):  # Personal.cpp:93-101: the epoch is read when the task is queued
        self.sim.tasks.append((self.epoch if epoch is None else epoch, self.sim.gen if gen is None else gen, fn, label))

    def is_member(self, a):  # Personal.cpp IsMember
        return a is not None and a.fid != PLAYER and a.teammate and a.commander is None and not a.dead and \
            (not a.waiting or 'waiting_not_party' not in self.fix)

    def party_now(self):  # Personal.cpp:390-406: every high-process actor is visited
        party = []
        for a in self.w.actors.values():
            self.op()
            if self.is_member(a) and a.loaded and a.dist <= PARTY_RANGE:
                party.append(a)
        return party

    def allowed(self, npc, kind, every):  # Personal.cpp:410-419
        self.op()
        key = (kind << 32) | npc
        last = self.repeat.get(key)
        if last is not None and self.now() - last < every:
            return False
        self.repeat[key] = self.now()
        return True

    def pickpocket_active(self):  # Personal.cpp:132
        return self.now() < self.pp_until

    # -- the 1 s poll: Personal.cpp:163-172 -----------------------------------------------------------------------------
    def check_crime(self):  # Personal.cpp:135-159
        total = self.w.bounty
        rose = self.crime_total >= 0 and total > self.crime_total + 0.5
        self.crime_total = total
        if not rose:
            return
        now = self.now()
        take_after = self.last_take is not None and self.last_take[2] > self.pp_until
        if 'take_after_pickpocket' not in self.fix:
            take_after = False
        target = self.get(self.pp_target)
        if target and now < self.pp_until + CAUGHT and not take_after:
            self.send('MLWW_Caught', 'pickpocketing', 0.0, target.fid)
            self.pp_target = None
            return
        if self.last_take and now - self.last_take[2] < CAUGHT:
            self.send('MLWW_Caught', self.last_take[1], 0.0, ('base', self.last_take[0]))
            self.last_take = None

    def check_party(self):  # Personal.cpp:422-462
        p = self.w.player
        now = self.now()
        party = self.party_now()
        self.health[PLAYER] = p.hp
        for m in party:
            self.op()
            self.health[m.fid] = m.hp
        if p.combat:
            if not self.in_fight:
                self.in_fight, self.fight_start = True, now
                self.sim.fight_started(now)
            self.last_combat = now
            for m in party:
                self.op()
                if m.combat:
                    self.fighters.add(m.fid)
            return
        if not self.in_fight or now - self.last_combat < FIGHT_QUIET:
            return
        self.in_fight = False
        if self.last_combat - self.fight_start >= MIN_FIGHT:
            for m in party:
                self.op()
                if m.fid in self.fighters:
                    self.send('MLWW_Fought', '', 0.0, m.fid)
        self.fighters.clear(); self.defenders.clear(); self.player_attackers.clear(); self.last_attacker.clear()

    # -- sinks: run in the event ----------------------------------------------------------------------------------------
    def hit_sink(self, cause, target, hostile_source, at_hit):  # Personal.cpp:738-749 then 534-566
        self.party_hit_event(cause, target, hostile_source, at_hit)
        if target.kind == 'chest' or cause.fid != PLAYER:
            return
        if 'struck_party' in self.fix and (target.teammate or target.commander is not None):
            return
        hostile = target.hostile
        self.task(lambda: self.on_hit(target.fid, hostile_source, hostile), 'OnHit')

    def party_hit_event(self, cause, target, hostile_source, at_hit):  # Personal.cpp:536-566
        if cause is target:
            return
        by_player, on_player = cause.fid == PLAYER, target.fid == PLAYER
        by_member = not by_player and self.is_member(cause)
        on_member = not on_player and self.is_member(target)
        commander = self.w.actors.get(cause.commander) if cause.commander is not None else None
        by_party = by_player or by_member or (commander is not None and (commander.fid == PLAYER or self.is_member(commander)))
        if 'summon_side' not in self.fix:
            by_party = by_player or by_member
        if not hostile_source:
            return
        if (on_player or on_member) and 'other_hit_guard' in self.fix:
            self.task(lambda: self.note_hit(target.fid, cause.fid), 'NoteHit')
        if (by_player and on_member) or (by_member and on_player):
            npc = target.fid if by_player else cause.fid
            when, epoch, gen = self.now(), self.epoch, self.sim.gen
            self.sim.run_later(RECHECK, lambda: self.task(lambda: self.on_friendly_hit(target.fid, npc, by_player, at_hit, when),
                                                          'OnFriendlyHit', epoch if 'epoch' in self.fix else None, gen))
        elif not by_party and (on_player or on_member):
            self.task(lambda: self.on_attacked(target.fid, cause.fid), 'OnAttacked')
        elif by_member and not on_player and not on_member:
            self.task(lambda: self.on_member_struck(cause.fid, target.fid), 'OnMemberStruck')

    def bleedout_sink(self, a):  # Personal.cpp:568-587
        if not self.is_member(a):
            return

        def run():
            who = self.get(a.fid)
            if not who:
                return
            self.sim.touch_fight_state('Bleedout')
            attacker = None
            last = self.last_attacker.get(a.fid)
            self.op()
            if last and self.now() - last[1] <= RESCUE:
                attacker = last[0]
            self.down[a.fid] = (attacker, self.now() + RESCUE)
        self.task(run, 'Bleedout')

    def magic_sink(self, caster, target, beneficial_health):  # Personal.cpp:616-640
        if caster is target or PLAYER not in (caster.fid, target.fid):
            return
        by_player = caster.fid == PLAYER
        npc = target if by_player else caster
        if not self.is_member(npc) or not beneficial_health:
            return
        before, epoch, gen = target.hp, self.epoch, self.sim.gen
        self.sim.run_later(RECHECK, lambda: self.task(lambda: self.on_heal_landed(target.fid, npc.fid, by_player, before),
                                                      'OnHealLanded', epoch if 'epoch' in self.fix else None, gen))

    def death_sink(self, victim, killer):  # Personal.cpp:732-737 and 679-693
        p = self.w.player
        if killer is not None and victim.fid != PLAYER and not victim.teammate:
            commander = self.w.actors.get(killer.commander) if killer.commander is not None else None
            credit = commander or killer
            if credit.fid == PLAYER or self.is_member(credit):
                hostile = victim.hostile
                self.task(lambda: self.on_kill(victim, credit.fid, hostile), 'OnKill')
        hostile, ally = victim.hostile, victim.teammate or victim.commander is not None  # read in the event
        self.task(lambda: self.on_death(victim, killer, hostile, ally), 'OnDeath')

    def activate_sink(self, target):  # Personal.cpp OnActivate: sleep read now, event from a task
        if 'sneak_no_wake' in self.fix and self.w.player.sneaking:
            return
        if target.kind in ('chest',) or target.dead or target.fid == PLAYER or not target.sleeping:
            return
        hour = self.w.game_hours % 24
        if 'sneak_no_wake' not in self.fix:
            self.task(lambda: self.get(target.fid) and self.send('MLWW_Woken', '', hour, target.fid), 'Woken')
            return
        epoch, gen = self.epoch, self.sim.gen  # OnWakeCheck a moment later: only someone who got up was woken

        def check():
            a = self.get(target.fid)
            if a and not a.sleeping:
                self.send('MLWW_Woken', '', hour, target.fid)
        self.sim.run_later(1.0, lambda: self.task(check, 'Woken', epoch, gen))

    def container_sink(self, frm, to, item, count, ref_owner=None):  # Personal.cpp:756-760 and 233-244
        owner = None
        if to == PLAYER:  # OwnerOfTake, read in the event
            src = self.w.actors.get(frm)
            if src is not None and src.kind == 'chest':
                owner = getattr(src, 'owner', None)
            elif frm == 0:
                owner = ref_owner
        self.task(lambda: self.on_moved(frm, to, item, count, owner), 'OnMoved')

    def menu_sink(self, name, opening):  # Personal.cpp:761-766
        if name in ('ContainerMenu', 'BarterMenu'):
            self.task(lambda: self.on_menu(name, opening), 'OnMenu')

    # -- tasks: main thread ---------------------------------------------------------------------------------------------
    def on_death(self, victim, killer, hostile=True, ally=False):  # Personal.cpp OnDeath
        if victim.fid == PLAYER:
            return
        by_player = killer is not None and killer.fid == PLAYER
        if 'murder_victim' in self.fix and by_player and not ally and victim.npc and (not hostile or victim.fid in self.assaulted):
            self.send('MLWW_Murder', '', 0.0, victim.fid)
        if not victim.unique:
            return
        self.send('MLWW_Died', '', 1.0 if killer is not None and killer.fid == PLAYER else 0.0, victim.fid)

    def on_hit(self, fid, hostile_source, was_hostile):  # Personal.cpp:193-210
        a = self.get(fid)
        if not a or a.dead or a.fid == PLAYER or was_hostile or not hostile_source:
            return
        if 'murder_victim' in self.fix:
            if len(self.assaulted) >= 256:
                self.assaulted.clear()
            self.assaulted.add(fid)
        self.op()
        last = self.last_hit.get(fid, -1e18)
        if self.now() - last < HIT_REPEAT:
            return
        self.last_hit[fid] = self.now()
        self.send('MLWW_Struck', '', 0.0, fid)

    def on_moved(self, frm, to, item, count, owner):  # Personal.cpp:269-310
        if count <= 0:
            return
        barter = 'BarterMenu' in self.w.menus
        if frm == PLAYER and to != PLAYER:
            if barter:
                if item != 'Gold':
                    self.op()
                    self.barter_sold[item] = self.barter_sold.get(item, 0) + count
                elif 'trade_both_ways' in self.fix:
                    self.barter_spent += count
                return
            actor = self.get(to)
            if not actor or actor.dead or actor.kind == 'chest' or self.pickpocket_active():
                return
            gift_menu = 'GiftMenu' in self.w.menus
            if 'follower_gold_net' in self.fix:
                if not gift_menu and actor.teammate:
                    return
            elif actor.teammate and item != 'Gold':
                return
            self.send('MLWW_GiftMenu' if gift_menu else 'MLWW_Gift', item, float(count), actor.fid)
            return
        if to == PLAYER and barter and item == 'Gold' and 'trade_both_ways' in self.fix:
            self.barter_earned += count
        if to != PLAYER or self.pickpocket_active() or (barter and 'barter_take' in self.fix):
            return
        if owner is not None:
            self.last_take = (owner, 'theft', self.now())

    def on_menu(self, name, opening):  # Personal.cpp:312-355
        if name == 'ContainerMenu':
            if opening and self.w.container_mode == 'pickpocket':
                self.pp_target = self.w.menu_target
                self.pp_until = 1e18
            elif opening and self.w.container_mode == 'npc' and 'follower_gold_net' in self.fix:
                a = self.get(self.w.menu_target)
                self.trade_target = a.fid if a and not a.dead and a.teammate else None
                self.trade_gold = self.w.gold[a.fid] if a else 0
            elif not opening and (self.pickpocket_active() if 'pickpocket_close' in self.fix else self.pp_target is not None):
                self.pp_until = self.now()
            if not opening:
                f = self.get(self.trade_target)
                self.trade_target = None
                given = self.w.gold[f.fid] - self.trade_gold if f and not f.dead else 0
                if given > 0:
                    self.send('MLWW_Gift', 'Gold', float(given), f.fid)
            return
        if opening:
            self.barter_target = self.w.menu_target
            self.barter_gold = self.w.gold[PLAYER]
            self.barter_sold = {}
            self.barter_spent = self.barter_earned = 0
            return
        merchant = self.get(self.barter_target)
        self.barter_target = None
        if not merchant:
            return
        delta = self.w.gold[PLAYER] - self.barter_gold
        chest = self.w.gold[merchant.merchant_chest] if merchant.merchant_chest else -1
        if 'trade_both_ways' in self.fix:
            spent, earned = self.barter_spent, self.barter_earned
            if spent == 0 and earned == 0:
                spent, earned = max(-delta, 0), max(delta, 0)
            self.barter_spent = self.barter_earned = 0
            if spent > 0 or earned > 0:
                self.send('MLWW_Trade', f'{chest}|{spent}|{earned}', float(delta), merchant.fid)
        elif delta != 0:
            self.send('MLWW_Trade', str(chest), float(delta), merchant.fid)
        if self.barter_sold:
            self.op(len(self.barter_sold))
            best = max(self.barter_sold.items(), key=lambda kv: kv[1])
            self.send('MLWW_TradeGoods', best[0], float(best[1]), merchant.fid)

    def on_friendly_hit(self, target_fid, npc_fid, by_player, at_hit, when):  # Personal.cpp:464-488
        target, npc = self.get(target_fid), self.get(npc_fid)
        if not target or not npc:
            return
        self.op()
        hit = self.party_hits.get(target_fid)
        if hit is not None:
            hitter = PLAYER if by_player else npc_fid
            if (hit['when'] if hit['cause'] != hitter else hit['other']) + HEALTH_READ >= when:
                return
        before = at_hit
        self.op()
        if target_fid in self.health:
            before = max(before, self.health[target_fid])
        if target.hp >= before - 0.5 or not self.allowed(npc_fid, 1 if by_player else 2, FRIENDLY_REPEAT):
            return
        self.send('MLWW_FriendlyFire', '', 1.0 if by_player else 0.0, npc_fid)

    def note_hit(self, target_fid, cause_fid):  # Personal.cpp:512-520
        self.op()
        hit = self.party_hits.setdefault(target_fid, {'cause': 0, 'when': -1e18, 'other': -1e18})
        if hit['cause'] != cause_fid:
            hit['other'], hit['cause'] = hit['when'], cause_fid
        hit['when'] = self.now()

    def on_attacked(self, target_fid, attacker_fid):  # Personal.cpp:490-510
        target, attacker = self.get(target_fid), self.get(attacker_fid)
        if not target or not attacker:
            return
        self.sim.touch_fight_state('OnAttacked')
        now = self.now()
        if target_fid != PLAYER:
            self.op()
            self.last_attacker[target_fid] = (attacker_fid, now)
            return
        if len(self.player_attackers) >= 64:
            self.op(len(self.player_attackers))
            self.player_attackers.clear()
        self.op()
        self.player_attackers[attacker_fid] = now
        if target.hp / target.maxhp < LOW_HEALTH:
            self.player_low = (attacker_fid, now + RESCUE)

    def on_member_struck(self, member_fid, target_fid):  # Personal.cpp:522-532
        member = self.get(member_fid)
        self.op()
        attacked = self.player_attackers.get(target_fid)
        if not member or attacked is None or self.now() - attacked > DEFEND:
            return
        self.op()
        if member_fid not in self.defenders:
            self.defenders.add(member_fid)
            self.send('MLWW_Defended', '', 0.0, member_fid)

    def on_heal_landed(self, target_fid, npc_fid, by_player, before):  # Personal.cpp:589-614
        target, npc = self.get(target_fid), self.get(npc_fid)
        if not target or not npc:
            return
        least = max(1.0, target.maxhp * 0.005)
        if target.hp - before < least:
            return
        if by_player:
            self.op()
            down = self.down.get(npc_fid)
            if down is not None:
                if self.now() <= down[1]:
                    self.send('MLWW_Saved', 'heal', 1.0, npc_fid)
                del self.down[npc_fid]
        if self.allowed(npc_fid, 3 if by_player else 4, HEAL_REPEAT):
            self.send('MLWW_Healed', '', 1.0 if by_player else 0.0, npc_fid)

    def on_kill(self, victim, killer_fid, was_hostile):  # Personal.cpp:643-677
        killer = self.get(killer_fid)
        if not killer:
            return
        now = self.now()
        if killer_fid == PLAYER:
            for fid in list(self.down):
                self.op()
                attacker, until = self.down[fid]
                member = self.w.actors.get(fid)
                if now > until:
                    del self.down[fid]
                elif member and (not member.dead or 'dead_saved' not in self.fix) and attacker == victim.fid and self.get(attacker) is not None:
                    self.send('MLWW_Saved', 'kill', 1.0, fid)
                    del self.down[fid]
        elif self.player_low and self.player_low[0] == victim.fid and self.get(self.player_low[0]) is not None and now <= self.player_low[1]:
            self.send('MLWW_Saved', 'kill', 0.0, killer_fid)
            self.player_low = None
        self.op()
        if not was_hostile and victim.fid not in self.player_attackers:
            return
        score = min(victim.level, 999) + (1000 if victim.unique else 0) + (2000 if victim.dragon else 0)
        self.send('MLWW_Kill', victim.name, float(score), killer_fid)

    def reset_fight(self):  # Personal.cpp:785-805
        if 'epoch' in self.fix:
            self.epoch += 1
        if 'reset_all' in self.fix:
            self.crime_total, self.last_take, self.pp_target, self.pp_until = -1.0, None, None, -1e9
            self.barter_target, self.barter_sold = None, {}
            self.last_hit.clear(); self.repeat.clear(); self.party_hits.clear()
            self.trade_target, self.trade_gold, self.barter_spent, self.barter_earned = None, 0, 0, 0
            self.assaulted.clear()
        self.in_fight = False
        self.fighters.clear(); self.defenders.clear(); self.player_attackers.clear(); self.last_attacker.clear()
        self.down.clear(); self.player_low = None; self.health.clear()

    def fight_state_empty(self):
        return not (self.fighters or self.defenders or self.player_attackers or self.last_attacker or self.down or
                    self.player_low or self.health or self.in_fight)


# ---------------------------------------------------------------------------------------------------------------------
# Papyrus (MLWW_Personal.psc, MLWW_Facts.psc, MLWW_State.psc CheckDungeons). StorageUtil belongs to the save.
# ---------------------------------------------------------------------------------------------------------------------

class Papyrus:
    def __init__(self, sim):
        self.sim = sim
        self.store = {}            # (form, key) -> int | float | str | list
        self.stale = []            # FormList KEY_STALE on the quest
        self.pending = False       # factWritePending
        self.update_due = None     # RegisterForSingleUpdate
        self.queued_at = {}        # model only: when each stale NPC was queued
        self.calls = 0

    def snapshot(self):
        due = None if self.update_due is None else self.update_due - self.sim.now
        return copy.deepcopy((self.store, self.stale, self.pending, due))

    def restore(self, snap):
        self.store, self.stale, self.pending, due = copy.deepcopy(snap)
        self.update_due = None if due is None else self.sim.now + due
        self.queued_at = {f: self.sim.now for f in self.stale}

    # StorageUtil
    def gi(self, form, key, default=0):
        self.calls += 1
        return self.store.get((form, key), default)

    def si(self, form, key, value):
        self.calls += 1
        self.store[(form, key)] = value

    def adj(self, form, key, n):
        self.calls += 1
        self.store[(form, key)] = self.store.get((form, key), 0) + n

    def lst(self, form, key):
        self.calls += 1
        return self.store.setdefault((form, key), [])

    def today(self):
        return self.sim.world.day()

    def register(self):  # MLWW_Personal.psc:37-57
        self.pending = False
        if self.stale:
            self.queue(None)

    # Records: MLWW_Personal.psc:63-234
    def handle(self, name, text, num, sender):
        w = self.sim.world
        a = w.actors.get(sender) if isinstance(sender, int) else None
        if name == 'MLWW_Died':
            self.si(sender, 'MLWW_DiedDay', w.game_hours / 24); self.si(sender, 'MLWW_DiedByPlayer', int(num))
            if num > 0 and 'murder_victim' not in self.sim.fix:  # the old OnDied stamped every unique the player killed
                self.si(None, 'MLWW_LastMurderDay', w.game_hours / 24)
                self.sim.check_murder_stamp(sender)
        elif name == 'MLWW_Murder':  # MLWW_Personal.OnMurder
            self.si(None, 'MLWW_LastMurderDay', w.game_hours / 24)
            self.sim.check_murder_stamp(sender)
        elif name == 'MLWW_Struck':
            self.si(sender, 'MLWW_StruckDay', w.game_hours / 24)
        elif name == 'MLWW_Woken':
            self.si(sender, 'MLWW_WokenAt', w.game_hours / 24); self.si(sender, 'MLWW_WokenHour', num)
        elif name in ('MLWW_Gift', 'MLWW_GiftMenu'):
            self.record_gift(sender, text, int(num), name == 'MLWW_Gift')
        elif name == 'MLWW_Trade':
            self.on_trade(sender, text, num)
        elif name == 'MLWW_Caught':  # CaughtKey: an owner base, a named NPC's base, else the actor itself
            key = ('base', sender[1]) if isinstance(sender, tuple) else (('base', a.base) if a and a.unique else sender)
            self.si(key, 'MLWW_CaughtDay', w.game_hours / 24); self.si(key, 'MLWW_CaughtKind', text)
        elif name == 'MLWW_TradeGoods':
            if text:
                self.goods(sender, text, int(num)); self.queue(sender)
        elif name == 'MLWW_Healed':
            self.count(sender, 'MLWW_HealedByPlayer' if num > 0 else 'MLWW_HealedPlayer', 'MLWW_HealedDay')
            if num > 0:
                self.sim.scores.append((sender, 'care'))
            self.queue(sender)
        elif name == 'MLWW_Saved':
            self.count(sender, 'MLWW_SavedByPlayer' if num > 0 else 'MLWW_SavedPlayer', 'MLWW_SavedDay')
            self.queue(sender)
        elif name == 'MLWW_Kill':  # MLWW_Personal.psc:193-203
            score = int(num)
            self.best(None, text, score)
            for m in self.sim.plugin.party_now():
                self.calls += 1
                if m.waiting:
                    self.sim.violate('waiting_credited', f'{m.name} was waiting elsewhere but got a kill')
                if m.fid == sender:
                    self.adj(m.fid, 'MLWW_KillsOwn', 1)
                elif sender == PLAYER:
                    self.adj(m.fid, 'MLWW_KillsPlayer', 1)
                self.best(m.fid, text, score)
                self.queue(m.fid)
        elif name == 'MLWW_FriendlyFire':
            self.count(sender, 'MLWW_HitByPlayer' if num > 0 else 'MLWW_HitPlayer', 'MLWW_HitDay'); self.queue(sender)
        elif name == 'MLWW_Fought':
            self.count(sender, 'MLWW_Fought', 'MLWW_FoughtDay'); self.queue(sender)
        elif name == 'MLWW_Defended':
            self.count(sender, 'MLWW_Defended', 'MLWW_DefendedDay'); self.queue(sender)

    def record_gift(self, form, item, count, score):  # MLWW_Personal.psc:92-116
        if not item:
            return
        if score and (item != 'Gold' or count >= 50):  # small change is remembered, not scored
            self.sim.scores.append((form, 'gifts'))
        today, gifts = self.today(), self.lst(form, 'MLWW_Gifts')
        if gifts:
            d, c, n = gifts[-1].split('|', 2)
            if int(d) == today and n == item:
                gifts[-1] = f'{today}|{int(c) + count}|{item}'
                return
        gifts.append(f'{today}|{count}|{item}')
        while len(gifts) > 3:
            gifts.pop(0)

    def on_trade(self, form, text, num):  # MLWW_Personal.psc OnTrade, MLWW_Facts.psc Trade
        parts = text.split('|')
        if len(parts) == 3:
            spent, earned = int(parts[1]), int(parts[2])
        else:
            spent, earned = max(-int(num), 0), max(int(num), 0)
        if spent <= 0 and earned <= 0:
            return
        today = self.today()
        new_day = self.gi(form, 'MLWW_TradeDay', -1) != today
        if new_day:
            self.si(form, 'MLWW_TradeDay', today); self.si(form, 'MLWW_TradeBought', 0); self.si(form, 'MLWW_TradeSold', 0)
        if earned > 0:
            self.adj(form, 'MLWW_SoldTotal', earned)
        if spent > 0:
            self.adj(form, 'MLWW_SpentTotal', spent)
        if new_day:
            self.adj(form, 'MLWW_Visits', 1)
        self.queue(form)
        self.adj(form, 'MLWW_TradeSold', earned)
        self.adj(form, 'MLWW_TradeBought', spent)
        self.si(form, 'MLWW_ChestDay', self.sim.world.game_hours / 24)  # Line() reads the chest live

    def goods(self, form, item, count):  # MLWW_Facts.psc:26-39
        names, counts = self.lst(form, 'MLWW_GoodsNames'), self.lst(form, 'MLWW_GoodsCounts')
        if item in names:
            counts[names.index(item)] += count
            return
        if len(names) >= 8:
            least = min(range(len(counts)), key=lambda i: (counts[i], -i))
            names.pop(least); counts.pop(least)
        names.append(item); counts.append(count)

    def count(self, form, key, day_key):  # MLWW_Facts.psc:56-59
        self.adj(form, key, 1); self.si(form, day_key, self.today())

    def best(self, form, name, score):  # MLWW_Facts.psc:72-78
        if name and score > self.gi(form, 'MLWW_BestScore', -1):
            self.si(form, 'MLWW_BestScore', score); self.si(form, 'MLWW_BestName', name); self.si(form, 'MLWW_BestDay', self.today())

    # QueueFacts: MLWW_Personal.psc:237-260
    def queue(self, form):
        if form is not None:
            self.calls += 1 + len(self.stale)  # FormListAdd without duplicates scans the list
            if form not in self.stale:
                self.stale.append(form)
                self.queued_at.setdefault(form, self.sim.now)
        if not self.pending:
            self.pending = True
            self.update_due = self.sim.now + FACT_DELAY

    def on_update(self):
        self.pending, self.update_due = False, None
        for i in range(len(self.stale) - 1, -1, -1):
            form = self.stale.pop(i)
            self.queued_at.pop(form, None)
            self.sim.sync(form)

    # MLWW_State.psc:49-74
    def check_dungeons(self, left, after_wait):
        cleared = self.sim.world.stat_dungeons
        seen = self.gi(None, 'MLWW_DungeonsSeen', -1)
        if cleared == seen:
            return
        self.si(None, 'MLWW_DungeonsSeen', cleared)
        if seen < 0 or cleared < seen:
            return
        self.sim.later(DUNGEON_WAIT, lambda: after_wait(left, cleared - seen))

    def credit_dungeon(self, left, n):
        for m in self.sim.plugin.party_now():
            if m.waiting:
                self.sim.violate('waiting_credited', f'{m.name} was waiting elsewhere but got the dungeon')
            self.adj(m.fid, 'MLWW_Dungeons', n); self.si(m.fid, 'MLWW_DungeonDay', self.today()); self.si(m.fid, 'MLWW_DungeonLast', left)
            self.sim.sync(m.fid)


# MLWW_Facts.psc Sync (105-133) and its text functions (151-340), used by the join check and token test.
def facts_of(store, form, player, teammate):
    gi = lambda f, k, d=0: store.get((f, k), d)
    gs = lambda f, k: store.get((f, k), '')

    def times(n):  # Times
        return 'once' if n == 1 else 'twice' if n == 2 else f'{n} times'

    def saves(by_player, by_npc):  # Saves
        out = f'they saved you {times(by_player)}' if by_player > 0 else ''
        if by_npc > 0:
            out += (', ' if out else '') + f'you saved them {times(by_npc)}'
        return out

    def counts(what, to_npc, to_player):  # Counts
        if to_npc <= 0 and to_player <= 0:
            return ''
        out = what
        if to_npc > 0:
            out += f' {to_npc} to you'
        if to_npc > 0 and to_player > 0:
            out += ','
        if to_player > 0:
            out += f' {to_player} to them'
        return out

    def join(parts):  # Join
        out = '; '.join(p for p in parts if p)
        return f'With {player}: {out}' if out else ''

    def care():  # Care
        return join([saves(gi(form, 'MLWW_SavedByPlayer'), gi(form, 'MLWW_SavedPlayer')),
                     counts('heals', gi(form, 'MLWW_HealedByPlayer'), gi(form, 'MLWW_HealedPlayer')),
                     counts('hits', gi(form, 'MLWW_HitByPlayer'), gi(form, 'MLWW_HitPlayer'))])

    def enemy(f):  # EnemyText
        name, score = gs(f, 'MLWW_BestName'), gi(f, 'MLWW_BestScore', -1)
        return '' if not name or score < 0 else name if score >= 1000 else f'{name} (level {score})'

    def together():  # Together
        parts = [''] * 5
        fights = gi(form, 'MLWW_Fought')
        if fights == 1:
            parts[0] = '1 fight'
        elif fights > 1:
            parts[0] = f'{fights} fights'
        defended = gi(form, 'MLWW_Defended')
        if defended > 0 and fights > 0:
            parts[0] += f', defended them in {defended}'
        elif defended > 0:
            parts[1] = f'defended them {times(defended)}'
        own, theirs = gi(form, 'MLWW_KillsOwn'), gi(form, 'MLWW_KillsPlayer')
        if own > 0 or theirs > 0:
            parts[2] = f'kills you {own}, them {theirs}'
        n, name = gi(form, 'MLWW_Dungeons'), gs(form, 'MLWW_DungeonLast')
        if n == 1:
            parts[3] = f'cleared {name}' if name else 'cleared a dungeon'
        elif n > 1:
            parts[3] = f'cleared {n} dungeons' + (f', latest {name}' if name else '')
        mine, best = enemy(form), enemy(None)
        if not best or not teammate or gi(None, 'MLWW_BestScore', -1) <= gi(form, 'MLWW_BestScore', -1):
            best = ''
        if mine and best:
            parts[4] = f'strongest enemy {mine}, theirs {best}'
        elif mine:
            parts[4] = f'strongest enemy {mine}'
        elif best:
            parts[4] = f'their strongest enemy {best}'
        return join(parts)

    def approx(g):  # Approx
        if g < 10:
            return str(g)
        step = 10 if g < 1000 else 100
        return f'{(g + step // 2) // step * step:,}'

    def customer():  # Customer
        spent, sold = gi(form, 'MLWW_SpentTotal'), gi(form, 'MLWW_SoldTotal')
        if spent + sold < 50:
            return ''
        line = player
        if spent > 0:
            line += f' spent ~{approx(spent)} gold'
        if spent > 0 and sold > 0:
            line += ','
        if sold > 0:
            line += f' sold you ~{approx(sold)} in goods'
        visits = gi(form, 'MLWW_Visits')
        if visits > 1:
            line += f', {visits} visits'
        counts_, names = store.get((form, 'MLWW_GoodsCounts'), []), store.get((form, 'MLWW_GoodsNames'), [])
        if counts_:
            best = max(range(len(counts_)), key=lambda i: (counts_[i], i))
            line += f', mostly {names[best]}'
        return line

    day = lambda f, k: gi(f, k, -1)
    care_day = max(day(form, 'MLWW_SavedDay'), day(form, 'MLWW_HealedDay'), day(form, 'MLWW_HitDay'))
    together_day = max(day(form, 'MLWW_FoughtDay'), day(form, 'MLWW_DefendedDay'), day(form, 'MLWW_DungeonDay'), day(form, 'MLWW_BestDay'))
    rows = {
        'fact_saved': (care_day, 3, care()),
        'fact_fought': (together_day, 2, together()),
        'fact_customer': (-1, 1, customer()),
    }
    return {k: f'{d}|-1|{p}|{t}' for k, (d, p, t) in rows.items() if t}


# MLWW_Personal.psc:276-356: how many of the 8 item slots one NPC's state needs.
def line_items(store, form, base, now_days, worn, hub, unique=False):
    gi = lambda k, d=0: store.get((form, k), d)
    n = 0
    caught = store.get((('base', base) if unique else form, 'MLWW_CaughtDay'), -1.0)
    n += caught >= 0 and now_days - caught <= 30
    n += bool(worn)
    woken = gi('MLWW_WokenAt', -1.0)
    n += woken >= 0 and now_days - woken <= 0.05
    struck = gi('MLWW_StruckDay', -1.0)
    n += struck >= 0 and now_days - struck <= 30 and not (gi('MLWW_HitByPlayer') > 0 and hub)
    n += any(now_days - int(g.split('|')[0]) <= 31 for g in store.get((form, 'MLWW_Gifts'), []))
    if gi('MLWW_TradeDay', -1) == int(now_days):
        n += gi('MLWW_TradeBought') > 0
        n += gi('MLWW_TradeSold') > 0
    chest_day = gi('MLWW_ChestDay', -1.0)
    n += chest_day >= 0 and now_days - chest_day <= 2  # the live chest may be low: counted as a slot
    return n


# ---------------------------------------------------------------------------------------------------------------------
# The simulation
# ---------------------------------------------------------------------------------------------------------------------

class Sim:
    def __init__(self, seed, fixes, steps, verbose=False):
        self.rng = random.Random(seed)
        self.seed, self.fix, self.steps, self.verbose = seed, fixes, steps, verbose
        self.now, self.tl_counter = 0.0, 0
        self.world = World(self.rng, self.new_tl())
        self.plugin = Plugin(self, fixes)
        self.papyrus = Papyrus(self)
        self.tasks, self.jobs, self.world_later = deque(), [], []
        self.truth, self.delivered, self.scores = [], [], []
        self.violations = defaultdict(list)
        self.worst_ops, self.worst_calls = defaultdict(int), defaultdict(int)
        self.saves, self.facts_file = {}, {}
        self.loading, self.last_load, self.gen = False, 0.0, 0
        self.event_count = defaultdict(int)
        self.max_tokens, self.max_line_items = 0, 0
        self.dropped = 0
        self.poll()
        self.papyrus.register()

    def new_tl(self):
        self.tl_counter += 1
        return self.tl_counter

    # -- time ---------------------------------------------------------------------------------------------------------
    def run_later(self, delay, fn):  # Writer.cpp RunLater: the worker thread, on the wall clock
        self.jobs.append((self.now + delay, fn))

    def later(self, delay, fn):  # something the game does by itself a little later, in this game only
        self.world_later.append((self.now + delay, self.world.tl, fn))

    def poll(self):  # Personal.cpp:163-172: re-armed from the worker, never from inside the task
        def fire():
            self.tasks.append((None, self.gen, lambda: (self.plugin.check_crime(), self.plugin.check_party()), 'Poll'))
            self.poll()
        self.run_later(CRIME_POLL, fire)

    def advance(self, seconds):
        end = self.now + seconds
        while self.now < end:
            step = FRAME
            if not self.loading and self.rng.random() < 0.004:
                step = self.rng.uniform(0.2, 1.0)  # a hitch: the main thread is busy, tasks wait
            self.now = min(end, self.now + step) if self.loading else self.now + step
            for due, fn in sorted([j for j in self.jobs if j[0] <= self.now], key=lambda j: j[0]):
                self.jobs.remove((due, fn))
                fn()
            if self.loading:
                continue
            for job in sorted([j for j in self.world_later if j[0] <= self.now], key=lambda j: j[0]):
                self.world_later.remove(job)
                if job[1] == self.world.tl:
                    job[2]()
            self.run_tasks()
            if self.papyrus.update_due is not None and self.now >= self.papyrus.update_due:
                self.papyrus.on_update()
            self.check_batching()

    def run_tasks(self):
        for _ in range(len(self.tasks)):
            epoch, gen, fn, label = self.tasks.popleft()
            if epoch is not None and epoch != self.plugin.epoch:
                self.dropped += 1
                continue
            self.current_gen = gen
            before = self.plugin.ops
            fn()
            # beyond one pass over the loaded actors (PartyNow, Personal.cpp:390-406)
            self.worst_ops[label] = max(self.worst_ops[label], self.plugin.ops - before - len(self.world.actors))
            self.current_gen = None

    current_gen = None

    def touch_fight_state(self, where):
        # A task queued in an older game (before a load) that reaches the fight state now.
        if self.current_gen is not None and self.current_gen < self.gen:
            self.violate('leak_task', f'{where} queued before the load changed the fight state after it')

    # -- ground truth -------------------------------------------------------------------------------------------------
    def fact(self, kind, **data):
        self.truth.append(dict(kind=kind, tl=self.world.tl, t=self.now, **data))

    def seen(self, kind, window, **match):
        for f in reversed(self.truth):
            if self.now - f['t'] > window:
                break
            if f['kind'] == kind and f['tl'] == self.world.tl and all(f.get(k) == v for k, v in match.items()):
                return f
        return None

    def violate(self, kind, detail):
        self.violations[kind].append(f'seed {self.seed} t={self.now:.2f}: {detail}')

    # -- events reaching Papyrus --------------------------------------------------------------------------------------
    def deliver(self, name, text, num, sender):
        self.event_count[name] += 1
        self.delivered.append((self.now, self.world.tl, name, sender, num))
        a = self.world.actors.get(sender) if isinstance(sender, int) else None
        who = a.name if a else str(sender)
        ok = self.attribute(name, text, num, sender)
        if ok is not True:
            self.violate(ok, f'{name}({text!r}, {num}) sent for {who}')
        self.check_rate(name, num, sender)
        before, ops = self.papyrus.calls, self.plugin.ops
        self.papyrus.handle(name, text, num, sender)
        self.plugin.ops = ops  # MLWW_Native.Party() from Papyrus is not work done for the plugin's event
        self.worst_calls[name] = max(self.worst_calls[name], self.papyrus.calls - before)
        self.check_counts()

    def attribute(self, name, text, num, sender):
        """True when the event matches what really happened in the game loaded now, else the violation kind."""
        tl_any = lambda kind, window, **m: any(f['kind'] == kind and f['tl'] != self.world.tl and self.now - f['t'] <= window and
                                               all(f.get(k) == v for k, v in m.items()) for f in self.truth[-400:])
        wrong = lambda: 'wrong_save'
        if name == 'MLWW_Struck':
            a = self.world.actors.get(sender)
            if a and (a.teammate or a.commander is not None):
                return 'struck_teammate'
            return True if self.seen('hit', 2, cause=PLAYER, target=sender, hostile=False) else wrong()
        if name == 'MLWW_Murder':
            f = self.seen('death', 2, victim=sender, credit=PLAYER)
            return True if f and f.get('murder') else ('murder_of_enemy' if f else wrong())
        if name == 'MLWW_FriendlyFire':
            m = dict(cause=PLAYER, target=sender) if num > 0 else dict(cause=sender, target=PLAYER)
            if self.seen('hit', 2, dmg_pos=True, **m):
                return True
            if self.seen('hit', 2, **m):
                return 'friendly_fire_not_theirs'
            return wrong() if tl_any('hit', 10, **m) else 'friendly_fire_not_theirs'
        if name == 'MLWW_Healed':
            m = dict(caster=PLAYER, target=sender) if num > 0 else dict(caster=sender, target=PLAYER)
            return True if self.seen('heal', 2, **m) else wrong()
        if name == 'MLWW_Saved':
            a = self.world.actors.get(sender)
            if text == 'heal':
                return True if self.seen('heal', 2, caster=PLAYER, target=sender) and self.seen('bleedout', RESCUE + 2, who=sender) else wrong()
            if num > 0:
                if a is None or a.dead:
                    return 'saved_dead'
                return True if self.seen('bleedout', RESCUE + 2, who=sender) and self.seen('death', 2, credit=PLAYER) else wrong()
            return True if self.seen('low', RESCUE + 2) and self.seen('death', 2, credit=sender) else wrong()
        if name == 'MLWW_Defended':
            f = self.seen('hit', 2, cause=sender, enemy_of_player=True)
            if f:
                return True
            if self.seen('hit', 2, cause=sender, party_summon=True):
                return 'defended_summon'
            return wrong()
        if name == 'MLWW_Fought':
            f = self.seen('engaged', 3600, who=sender)
            return True if f and f['t'] >= self.last_load else wrong()
        if name == 'MLWW_Kill':
            return True if self.seen('death', 2, credit=sender, name=text) else wrong()
        if name == 'MLWW_Died':
            return True if self.seen('death', 2, victim=sender) else wrong()
        if name == 'MLWW_Woken':
            if self.seen('woken', 3, who=sender):
                return True
            return 'woken_while_sneaking' if self.seen('sneak_activate', 3, who=sender) else wrong()
        a = self.world.actors.get(sender) if isinstance(sender, int) else None
        if name == 'MLWW_Gift' and text == 'Gold' and a is not None and a.teammate:
            f = self.seen('follower_trade', 3, to=sender)
            return True if f and f['net'] == int(num) else 'gift_taken_back'
        if name in ('MLWW_Gift', 'MLWW_GiftMenu'):
            how = 'menu' if name == 'MLWW_GiftMenu' else 'other'
            if self.seen('gift', 2, to=sender, how=how, item=text):
                return True
            if self.seen('payment', 2, to=sender):
                return 'gift_is_payment'
            return wrong()
        if name == 'MLWW_Trade':
            f = self.seen('barter', 2, merchant=sender, net=int(num))
            if not f:
                return wrong()
            parts = text.split('|')
            return True if len(parts) == 3 and (int(parts[1]), int(parts[2])) == (f['spent'], f['earned']) else 'trade_net_only'
        if name == 'MLWW_TradeGoods':
            f = self.seen('barter', 2, merchant=sender)
            return True if f and f['sold'].get(text) == max(f['sold'].values()) == int(num) else wrong()
        if name == 'MLWW_Caught':
            base = sender[1] if isinstance(sender, tuple) else self.world.actors[sender].base
            f = self.seen('bounty', CRIME_POLL + CAUGHT + 1.5)
            victims = {(g['victim'], g['how']) for g in self.truth[-60:] if g['kind'] == 'bounty' and g['tl'] == self.world.tl and self.now - g['t'] <= CRIME_POLL + 2.5}
            if (base, text) in victims:
                return True
            if not f:
                return 'crime_across_load'
            if self.seen('bought', CAUGHT + 1.5, owner=base):
                return 'caught_purchase'
            if text == 'pickpocketing' and self.seen('take', CAUGHT + 1.5):
                return 'caught_newer_take' if self.seen('pickpocket_closed', CAUGHT + 1.5) else 'caught_wrong_owner'
            return 'caught_wrong_owner'
        return True

    def check_murder_stamp(self, victim):
        f = self.seen('death', 2, victim=victim, credit=PLAYER)
        if not (f and f.get('murder')):
            a = self.world.actors.get(victim)
            self.violate('murder_of_enemy', f'murder stamp from the death of {a.name if a else victim}, who was no murder victim')

    def check_rate(self, name, num, sender):
        every = {'MLWW_Struck': HIT_REPEAT, 'MLWW_FriendlyFire': FRIENDLY_REPEAT, 'MLWW_Healed': HEAL_REPEAT}.get(name)
        if every is None:
            return
        same = [t for t, tl, n, s, x in self.delivered[:-1] if n == name and s == sender and (name == 'MLWW_Struck' or x == num)
                and tl == self.world.tl and t >= self.last_load]
        if same and self.now - same[-1] < every - 1e-9:
            self.violate('rate', f'{name} for {sender:#x} again after {self.now - same[-1]:.1f} s')

    def check_counts(self):
        for (form, key), v in self.papyrus.store.items():
            values = v if isinstance(v, list) else [v]
            for x in values:
                if isinstance(x, (int, float)) and not -1 <= x <= INT_MAX:
                    self.violate('counts', f'{key} on {form} = {x}')
        for item, c in self.plugin.barter_sold.items():
            if not 0 < c <= INT_MAX:
                self.violate('counts', f'barter count {item} = {c}')

    def check_batching(self):
        for form, t in self.papyrus.queued_at.items():
            if self.now - t > FACT_DELAY + 1.5:
                self.violate('batching', f'{form} waited {self.now - t:.1f} s for its fact write')
                self.papyrus.queued_at[form] = self.now  # once per wait

    def sync(self, form):  # MLWW_Facts.psc:103-127: the file is shared by every save
        a = self.world.actors.get(form)
        if a is None or not isinstance(form, int):
            return
        self.facts_file[a.base] = facts_of(self.papyrus.store, form, 'Player', a.teammate)
        tokens = sum((len(v.split('|', 3)[3]) + 3) // 4 + 1 for v in self.facts_file[a.base].values())
        self.max_tokens = max(self.max_tokens, tokens)

    # -- game actions -------------------------------------------------------------------------------------------------
    def hit(self, cause, target, dmg, hostile_source=True):
        if target.dead or cause.dead:
            return
        w, p = self.world, self.world.player
        commander = w.actors.get(cause.commander) if cause.commander is not None else None
        party_side = cause.fid == PLAYER or cause.kind == 'follower' or (commander is not None and commander.kind in ('player', 'follower'))
        self.fact('hit', cause=cause.fid, target=target.fid, dmg_pos=dmg > 0, hostile=target.hostile,
                  enemy_of_player=bool(self.seen('hit', DEFEND, cause=target.fid, target=PLAYER)) and not (
                      target.commander is not None and w.actors.get(target.commander) is not None and w.actors[target.commander].kind in ('player', 'follower')),
                  party_summon=target.commander is not None and w.actors.get(target.commander) is not None and w.actors[target.commander].kind in ('player', 'follower'))
        if target.fid == PLAYER and not party_side and p.hp - dmg < p.maxhp * LOW_HEALTH:
            self.fact('low')
        post = self.rng.random() < 0.5  # the engine sends some hits after the damage, some before
        if post:
            self.damage(cause, target, dmg)
        self.plugin.hit_sink(cause, target, hostile_source, target.hp)
        if not post:
            self.later(FRAME, lambda: self.damage(cause, target, dmg))
        if cause.fid == PLAYER and not target.hostile and hostile_source:
            target.assaulted = True  # a murder if the player kills them later, even after they fought back
        if target.kind in ('townsfolk', 'guard', 'merchant') and cause.fid == PLAYER:
            target.hostile = True  # the hit makes them hostile; OnHit read it before
            if self.rng.random() < 0.5 and self.quiet_for_crime():
                self.bounty(40, None, 'assault')

    def damage(self, cause, target, dmg):
        if target.dead:
            return
        target.hp -= dmg
        if target.fid == PLAYER:
            target.hp = max(target.hp, 1.0)
            return
        if target.hp > 0:
            return
        if target.kind == 'follower' and cause.fid != PLAYER:  # protected: only the player can kill them
            target.hp = 0.0
            if not target.bleed:
                target.bleed = True
                self.fact('bleedout', who=target.fid)
                self.plugin.bleedout_sink(target)
                self.later(self.rng.uniform(8, 25), lambda: self.get_up(target))
            return
        self.die(target, cause)

    def get_up(self, a):
        if a.bleed and not a.dead:
            a.bleed, a.hp = False, a.maxhp * 0.2

    def die(self, victim, killer):
        victim.dead, victim.hp = True, 0.0
        commander = self.world.actors.get(killer.commander) if killer and killer.commander is not None else None
        credit = (commander or killer).fid if killer else None
        murder = credit == PLAYER and killer.fid == PLAYER and victim.npc and not victim.teammate and victim.commander is None and \
            (not victim.hostile or victim.assaulted)
        self.fact('death', victim=victim.fid, credit=credit, name=victim.name, murder=murder)
        self.plugin.death_sink(victim, killer)
        for s in self.world.actors.values():  # summons vanish with their summoner
            if s.commander == victim.fid and not s.dead:
                s.dead = True

    def heal(self, caster, target, amount, over_time=False):
        if target.dead or caster.dead:
            return
        rise = min(amount, target.maxhp - target.hp)
        if rise > max(1.0, target.maxhp * 0.005):
            self.fact('heal', caster=caster.fid, target=target.fid)
        self.plugin.magic_sink(caster, target, True)
        if over_time:
            for k in range(1, 13):
                self.later(0.25 * k, lambda: self._heal_tick(target, amount / 12))
        else:
            self.later(FRAME, lambda: self._heal_tick(target, amount))

    def _heal_tick(self, target, amount):
        if not target.dead:
            target.hp = min(target.maxhp, target.hp + amount)
            if target.bleed and target.hp > 0:
                target.bleed = False

    def bounty(self, amount, victim, how):
        self.world.bounty += amount
        self.fact('bounty', victim=victim, how=how)

    def container(self, frm, to, item, count, ref_owner=None):
        w = self.world
        if item == 'Gold':
            w.gold[frm] -= count
            if to:
                w.gold[to] += count
        self.plugin.container_sink(frm, to, item, count, ref_owner)

    def menu(self, name, opening, mode=None, target=None):
        w = self.world
        if opening:
            w.menus.add(name)
            w.container_mode, w.menu_target = mode, target
        else:
            w.menus.discard(name)
        self.plugin.menu_sink(name, opening)

    # -- scenarios ----------------------------------------------------------------------------------------------------
    def party(self):
        return [a for a in self.world.of('follower') if a.dist <= PARTY_RANGE]

    def spawn_wave(self):
        w = self.world
        n = self.rng.randint(3, 15)
        for i in range(n):
            e = w.add(Actor(w.fid(), 'enemy', self.rng.choice(('Bandit', 'Draugr Wight', 'Bandit Chief', 'Necromancer', 'Frost Troll')),
                            self.rng.uniform(40, 250), level=self.rng.randint(1, 60)))
            if self.rng.random() < 0.05:
                e.unique, e.name = True, self.rng.choice(('Vilkas', 'Karstaag', 'Krosis'))
            if self.rng.random() < 0.03:
                e.dragon, e.name, e.hp = True, 'Ancient Dragon', 900.0
            if e.name == 'Necromancer':
                w.add(Actor(w.fid(), 'enemy', 'Risen Thrall', 60.0, commander=e.fid))
        w.player.combat = True

    def summon(self, by):
        w = self.world
        s = w.add(Actor(w.fid(), 'summon', 'Flame Atronach', 120.0, commander=by.fid, teammate=by.fid == PLAYER))
        return s

    def fight_round(self):
        w, rng = self.world, self.rng
        enemies = [e for e in w.of('enemy') if e.loaded]
        if not enemies:
            if w.player.combat:
                w.player.combat = False
                for m in w.of('follower'):
                    m.combat = False
            return
        p = w.player
        party = [m for m in self.party() if not m.bleed]
        summons = [s for s in w.of('summon')]
        for m in party:
            if not m.combat and rng.random() < 0.8:
                m.combat = True
            if m.combat:
                self.fact('engaged', who=m.fid)
        roll = rng.random()
        e = rng.choice(enemies)
        if roll < 0.25:  # an enemy hits the player or a member (sometimes area damage on several)
            victims = [p] + party if rng.random() < 0.2 else [rng.choice([p] + party)]
            for v in victims:
                self.hit(e, v, rng.uniform(5, 60))
        elif roll < 0.45:  # the player attacks; area spells catch whoever is near
            targets = [e] + ([x for x in party + summons + [rng.choice(enemies)] if rng.random() < 0.4] if rng.random() < 0.25 else [])
            rng.shuffle(targets)
            for t in targets:
                friendly = t.kind in ('follower', 'summon')
                self.hit(p, t, 0.0 if friendly and rng.random() < 0.35 else rng.uniform(5, 80))
        elif roll < 0.65 and party:  # a member attacks; now and then the player or a summon is in the way
            m = rng.choice(party)
            r = rng.random()
            if r < 0.05:
                self.hit(m, p, 0.0 if rng.random() < 0.35 else rng.uniform(3, 30))
            elif r < 0.10 and summons:
                self.hit(m, rng.choice(summons), rng.uniform(3, 30))
            else:
                self.hit(m, e, rng.uniform(5, 60))
        elif roll < 0.75 and summons:  # a summon fights; its explosions reach the party too
            s = rng.choice(summons)
            for t in [e] + ([x for x in [p] + party if rng.random() < 0.3] if rng.random() < 0.3 else []):
                self.hit(s, t, rng.uniform(5, 40))
        elif roll < 0.85:  # heals: single, area, over time, both ways
            hurt = [x for x in party if x.hp < x.maxhp]
            r = rng.random()
            if r < 0.4 and hurt:
                self.heal(p, rng.choice(hurt), rng.uniform(20, 120), over_time=rng.random() < 0.3)
            elif r < 0.6:
                for x in [p] + party:
                    self.heal(p, x, rng.uniform(20, 80))
            elif party:
                self.heal(rng.choice(party), p, rng.uniform(20, 80), over_time=rng.random() < 0.3)
        elif roll < 0.92:
            r = rng.random()
            if r < 0.5:
                self.summon(p)
            elif party:
                self.summon(rng.choice(party))
        else:  # the player finishes off an enemy, sometimes with an area blast that also hits a downed member
            down = [m for m in w.of('follower') if m.bleed]
            if down and rng.random() < 0.3:
                for t in rng.sample([e, rng.choice(down)], 2):
                    self.hit(p, t, 1000.0)
            else:
                self.hit(p, e, 1000.0)
        for s in summons:
            if rng.random() < 0.02:
                s.dead = True  # dismissed or timed out

    def barter(self):
        w, rng = self.world, self.rng
        m = rng.choice(w.of('merchant'))
        chest = w.actors[m.merchant_chest]
        self.menu('BarterMenu', True, target=m.fid)
        self.advance(0.2)
        net, sold, spent, earned = 0, defaultdict(int), 0, 0
        bought_owned = False
        for _ in range(rng.randint(1, 8)):
            price = rng.choice((5, 30, 120, 900))
            if rng.random() < 0.5 and w.gold[chest.fid] >= price:
                item = rng.choice(('Iron Dagger', 'Wolf Pelt', 'Garnet', 'Iron Dagger'))
                n = rng.randint(1, 5)
                self.container(PLAYER, chest.fid, item, n)
                self.container(chest.fid, PLAYER, 'Gold', price)
                net += price
                earned += price
                sold[item] += n
                bought_owned |= chest.owner is not None
            elif w.gold[PLAYER] >= price:
                self.container(chest.fid, PLAYER, rng.choice(('Bread', 'Steel Sword', 'Potion')), 1)
                self.container(PLAYER, chest.fid, 'Gold', price)
                net -= price
                spent += price
                bought_owned |= chest.owner is not None
            self.advance(rng.uniform(0.2, 1.5))
        self.menu('BarterMenu', False)
        self.fact('barter', merchant=m.fid, net=net, sold=dict(sold), spent=spent, earned=earned)
        if bought_owned:
            self.fact('bought', owner=chest.owner)
        self.advance(rng.uniform(0.1, 0.4))
        if rng.random() < 0.3 and self.quiet_for_crime():  # a bounty for something else right after (trespass)
            self.bounty(10, None, 'trespass')

    def quiet_for_crime(self):
        # A bounty with no owner this soon after a take or a pickpocket is read as caught by design: not generated.
        return not self.seen('take', CAUGHT + 1.5) and not self.seen('pickpocket_closed', CAUGHT + 1.5)

    def gift(self):
        w, rng = self.world, self.rng
        r = rng.random()
        to = rng.choice(w.of('townsfolk') + w.of('merchant') + w.of('follower'))
        item = rng.choice(('Gold', 'Silver Ring', 'Apple'))
        n = 100 if item == 'Gold' else 1
        if w.gold[PLAYER] < n:
            return
        if r < 0.35:
            self.menu('GiftMenu', True)
            if 'follower_gold_net' in self.fix or not (to.teammate and item != 'Gold'):
                self.fact('gift', to=to.fid, how='menu', item=item)
            self.container(PLAYER, to.fid, item, n)
            self.advance(0.3)
            self.menu('GiftMenu', False)
        elif r < 0.7:
            if not to.teammate:  # outside their inventory window nothing given to a follower is a gift
                self.fact('gift', to=to.fid, how='other', item=item)
            self.container(PLAYER, to.fid, item, n)
        else:  # MLWW_Crime.psc:118, the bribe
            guard = w.of('guard')[0]
            self.fact('payment', to=guard.fid)
            self.container(PLAYER, 0 if 'bribe_to_nobody' in self.fix else guard.fid, 'Gold', 100)

    def follower_trade(self):
        # The follower's inventory window: gold handed over and some or all of it taken back, then closed.
        w, rng = self.world, self.rng
        followers = w.of('follower')
        if not followers:
            return
        f = rng.choice(followers)
        moves = []
        held, purse = w.gold[f.fid], w.gold[PLAYER]
        for _ in range(rng.randint(1, 4)):
            if rng.random() < 0.55 and purse > 0:
                n = min(purse, rng.choice((1, 10, 60, 500)))
                moves.append((PLAYER, f.fid, n)); purse -= n; held += n
            elif held > 0:
                n = rng.choice((held, max(1, held // 2)))
                moves.append((f.fid, PLAYER, n)); purse += n; held -= n
        net = held - w.gold[f.fid]
        self.fact('follower_trade', to=f.fid, net=net)
        self.menu('ContainerMenu', True, mode='npc', target=f.fid)
        self.advance(0.2)
        for frm, to, n in moves:
            self.container(frm, to, 'Gold', n)
            self.advance(rng.uniform(0.1, 0.6))
        self.menu('ContainerMenu', False)

    def murder(self):
        # A townsperson killed by the player: at once, or struck first so they fight back (hostile when they die).
        w, rng = self.world, self.rng
        a = rng.choice(w.of('townsfolk'))
        if rng.random() < 0.5:
            self.hit(w.player, a, 1.0)
            self.advance(rng.uniform(0.2, 2.0))
        self.hit(w.player, a, 1000.0)
        self.advance(0.3)
        w.add(Actor(w.fid(), 'townsfolk', rng.choice(('Carlotta', 'Amren', 'Olfina')), 60.0))  # someone new moves in

    def follower_wait(self):
        followers = self.world.of('follower')
        if followers:
            f = self.rng.choice(followers)
            f.waiting = not f.waiting  # told to wait outside, or to come along again

    def settle(self):
        # The plugin reads the bounty once a second, so a bounty from something else in the second before a take or a
        # pickpocket reads as caught: a known limit of the design, not generated.
        if self.seen('bounty', CRIME_POLL + 0.5):
            self.advance(CRIME_POLL + 0.5)

    def pickpocket(self):
        w, rng = self.world, self.rng
        self.settle()
        a = rng.choice(w.of('townsfolk'))
        self.menu('ContainerMenu', True, mode='pickpocket', target=a.fid)
        self.advance(0.2)
        self.container(a.fid, PLAYER, 'Garnet', 1)
        if rng.random() < 0.3:
            self.container(PLAYER, a.fid, 'Poison', 1)  # reverse pickpocket: not a gift
        self.advance(rng.uniform(0.2, 1.0))
        caught = rng.random() < 0.4
        if caught:
            self.bounty(25, a.base, 'pickpocketing')
        self.menu('ContainerMenu', False)
        self.fact('pickpocket_closed')
        if caught:
            self.advance(1.2)  # the guard talks to the player first

    def steal(self):
        w, rng = self.world, self.rng
        chest = rng.choice([c for c in w.of('chest') if getattr(c, 'owner', None) and c.merchant_chest is None and
                            'chest' in c.name and not any(m.merchant_chest == c.fid for m in w.of('merchant'))] or [None])
        if chest is None:
            return
        self.settle()
        if rng.random() < 0.5:
            self.menu('ContainerMenu', True, mode='loot', target=chest.fid)
            self.advance(0.2)
            self.container(chest.fid, PLAYER, 'Silver Ring', 1)
            self.fact('take', owner=chest.owner)
            if rng.random() < 0.5:
                self.bounty(25, chest.owner, 'theft')
            self.advance(rng.uniform(0.05, 1.5))
            self.menu('ContainerMenu', False)
        else:  # picked up from the world
            self.container(0, PLAYER, 'Sweetroll', 1, ref_owner=chest.owner)
            self.fact('take', owner=chest.owner)
            if rng.random() < 0.5:
                self.bounty(5, chest.owner, 'theft')

    def steal_then_load(self):  # an unseen take, then straight into the other save (quick load)
        if self.saves:
            self.steal()
            self.load(seconds=self.rng.uniform(0.3, 1.2))

    def wake(self):
        a = self.rng.choice(self.world.of('townsfolk'))
        a.sleeping = self.rng.random() < 0.6
        p = self.world.player
        p.sneaking = self.rng.random() < 0.3  # sneaking: the pickpocket menu opens and they sleep on
        if a.sleeping:
            self.fact('sneak_activate' if p.sneaking else 'woken', who=a.fid)
        self.plugin.activate_sink(a)
        a.sleeping = a.sleeping and p.sneaking
        p.sneaking = False

    def strike_townsfolk(self):
        a = self.rng.choice(self.world.of('townsfolk') + self.world.of('merchant'))
        self.hit(self.world.player, a, self.rng.uniform(1, 10))

    def dungeon(self):
        w = self.world
        w.location = 'Bleak Falls Barrow'
        self.location_change('Whiterun')
        self.spawn_wave()
        for _ in range(40):
            self.fight_round(); self.advance(self.rng.uniform(0.05, 0.6))
        if self.rng.random() < 0.7:
            w.stat_dungeons += 1
            self.fact('cleared')
        w.location = 'Whiterun'
        self.location_change('Bleak Falls Barrow')

    def location_change(self, left):  # MLWW_PlayerAlias.psc OnLocationChange -> MLWW_State.LocationChanged
        self.papyrus.check_dungeons(left, self.papyrus.credit_dungeon)

    def fast_travel(self):
        w = self.world
        if w.player.combat:
            return
        for e in w.of('enemy'):
            e.loaded = False
        left = w.location
        w.location = self.rng.choice(('Riverwood', 'Solitude', 'Windhelm'))
        w.game_hours += self.rng.uniform(4, 40)
        for m in w.of('follower'):
            m.dist = 300.0 if self.rng.random() < 0.9 else 20000.0
        self.location_change(left)

    def save(self):
        slot = self.rng.choice('AB')
        self.saves[slot] = (copy.deepcopy(self.world), self.papyrus.snapshot())

    def load(self, new_game=False, seconds=None):
        if not new_game and not self.saves:
            return
        self.gen += 1
        self.plugin.reset_fight()  # kPreLoadGame, main.cpp
        self.loading = True
        self.advance(seconds or self.rng.uniform(1.0, 6.0))  # the load screen: the worker keeps running, tasks wait
        if new_game:
            self.world = World(self.rng, self.new_tl())
            self.papyrus.restore(({}, [], False, None))
        else:
            world, snap = self.saves[self.rng.choice(sorted(self.saves))]
            self.world = copy.deepcopy(world)
            self.world.tl = self.new_tl()
            self.papyrus.restore(snap)
        self.loading = False
        self.papyrus.register()  # OnPlayerLoadGame -> MLWW_Job.Register
        self.plugin.reset_fight()  # kPostLoadGame / kNewGame
        for m in self.world.of('follower'):
            if m.combat:
                self.fact('engaged', who=m.fid)  # a save made mid-fight goes on fighting
        if not self.plugin.fight_state_empty():
            self.violate('leak', 'fight state not empty after ResetFight')
        self.last_load = self.now

    def join(self):  # MantellaConversation_NPC_Added -> MLWW_Personal.OnNpcAdded: Sync, then Line
        w = self.world
        a = self.rng.choice(w.of('follower') + w.of('merchant') or [None])
        if a is None:
            return
        self.sync(a.fid)
        want = facts_of(self.papyrus.store, a.fid, 'Player', a.teammate)
        if self.facts_file.get(a.base) != want:
            self.violate('join', f'{a.name}: file facts differ from this save after the join')
        n = line_items(self.papyrus.store, a.fid, a.base, w.game_hours / 24, self.rng.random() < 0.3, True, a.unique)
        self.max_line_items = max(self.max_line_items, n)
        if n > 8:
            self.violate('line', f'{a.name}: Line() needs {n} of 8 slots')

    fight_started = lambda self, t: None

    def run(self):
        rng = self.rng
        actions = [(self.fight_burst, 30), (self.barter, 6), (self.gift, 6), (self.pickpocket, 4), (self.steal, 5),
                   (self.wake, 3), (self.steal_then_load, 1), (self.follower_trade, 4), (self.murder, 1), (self.follower_wait, 2), (self.strike_townsfolk, 3), (self.dungeon, 2), (self.fast_travel, 4), (self.save, 4),
                   (lambda: self.load(), 4), (lambda: self.load(new_game=True), 0.3), (self.join, 6), (self.idle, 6)]
        fns, weights = zip(*actions)
        for _ in range(self.steps):
            rng.choices(fns, weights)[0]()
            self.advance(rng.uniform(0.05, 1.0))
        self.advance(FACT_DELAY + 2)

    def idle(self):
        self.advance(self.rng.uniform(2, 20))

    def fight_burst(self):
        if not self.world.player.combat:
            self.spawn_wave()
        for _ in range(self.rng.randint(3, 25)):
            self.fight_round()
            self.advance(self.rng.uniform(0.03, 0.7))
            if self.rng.random() < 0.03:
                self.save()
            if self.rng.random() < 0.02:
                self.load()
                return
            if self.rng.random() < 0.003:
                self.load(new_game=True)
                return
        if self.rng.random() < 0.15:  # run through a load door: the fight ends behind the player
            for e in self.world.of('enemy'):
                e.loaded = False


def run_all(fixes, seeds, steps, verbose):
    total = defaultdict(list)
    ops, calls, events = defaultdict(int), defaultdict(int), defaultdict(int)
    tokens = line = dropped = 0
    for seed in range(seeds):
        sim = Sim(seed, fixes, steps, verbose)
        sim.run()
        for k, v in sim.violations.items():
            total[k] += v
        for k, v in sim.worst_ops.items():
            ops[k] = max(ops[k], v)
        for k, v in sim.worst_calls.items():
            calls[k] = max(calls[k], v)
        for k, v in sim.event_count.items():
            events[k] += v
        tokens, line, dropped = max(tokens, sim.max_tokens), max(line, sim.max_line_items), dropped + sim.dropped
        high = len(sim.world.actors)
    return total, ops, calls, events, tokens, line, dropped


def dungeon_race(fixed=True):
    """MLWW_State.psc CheckDungeons between two location changes whose threads interleave after QueryStat (a native
    call, so the script can be entered by another thread) and before SetIntValue. Returns the dungeons credited for 1
    cleared. fixed: the dungeonBusy flag is set before the first native call, so the second thread returns at once."""
    stat, store = 5, {'seen': 4}
    busy = False
    credited = 0
    threads = []
    for _ in range(2):                              # both threads enter before either reaches SetIntValue
        if fixed and busy:
            continue
        busy = True
        threads.append((stat, store['seen']))       # QueryStat, then GetIntValue
    for cleared, seen in threads:
        store['seen'] = cleared
        if cleared != seen and seen >= 0:
            credited += cleared - seen
    return credited


def report_evidence(crime, now, last_murder=-1.0, murder_hold=0, guard_hold=0, violent=0, struck=()):
    """MLWW_Crime.psc Report (CrimeGold) and NoEvidence: "" when the game backs a report. struck: (MLWW_StruckDay,
    is the guard or a teammate) for each talk member."""
    if crime in ('theft', 'pickpocketing'):
        return 'not reportable'  # CrimeGold 0: the game charged it when the player was caught
    if crime == 'murder':
        if last_murder < 0 or now - last_murder > 3.0:
            return 'no murder'
        if murder_hold < 0 or murder_hold != guard_hold:
            return 'not in this hold'
        return 'already priced' if violent >= 1000 else ''
    if crime != 'assault':
        return ''
    return '' if any(t >= 0 and now - t <= 1.0 and not own for t, own in struck) else 'no record'


def waive_twice(fixed=True):
    """MLWW_Crime.psc Settle: a Thane with a 30 gold bounty asks twice on one day. Returns how many waivers were given."""
    store, today, given = {}, 12, 0
    for _ in range(2):
        if not fixed or store.get('waive', -1) != today:
            store['waive'] = today
            given += 1
    return given


def free_clears(methods, speech, bounty, thane=True, fixed=True):
    """MLWW_Crime.psc Settle: the free clears given for one bounty asked again and again on one day (the bounty comes
    back each time). fixed: waiver and persuade share one day key, persuade needs Speech >= bounty."""
    store, today, given = {}, 12, 0
    for method in methods:
        if bounty <= 40 and thane and store.get('waive', -1) != today:
            store['waive'] = today
            given += 1
        elif method == 'persuade' and bounty <= 100:
            key = 'waive' if fixed else 'persuade'
            if store.get(key, -1) != today and (not fixed or speech >= bounty):
                store[key] = today
                given += 1
    return given


def quest_progress(completed, running, stage):
    """MLWW_State.psc WriteQuests: 0 not started, 1 running, 2 done."""
    if completed or (not running and stage > 0):
        return 2
    return 1 if running and stage > 0 else 0


def told_events(rows):
    """MLWW_State.psc Refresh: ids of the true rows told as events; rows a true row supersedes are left out.
    rows: (id, true, supersedes)."""
    gone = {s for rid, true, sup in rows if true for s in sup}
    return [rid for rid, true, sup in rows if true and rid not in gone]


def gift_scored(count):
    """MLWW_Personal.psc RecordGift: gold scores only from 50 septims, weight 0.5 to 5."""
    return min(max(count / 100.0, 0.5), 5.0) if count >= 50 else 0.0


def evidence_checks():
    cases = [
        (report_evidence('murder', 10.0) != '', 'murder with nobody killed by the player is refused'),
        (report_evidence('murder', 10.0, last_murder=8.5) == '', 'murder within 3 days of a kill by the player is taken'),
        (report_evidence('murder', 10.0, last_murder=6.0) != '', 'murder 4 days after the last kill is refused'),
        (report_evidence('murder', 10.0, last_murder=9.5, murder_hold=3, guard_hold=0) != '', 'murder in another hold is refused'),
        (report_evidence('murder', 10.0, last_murder=9.5, murder_hold=-1, guard_hold=-1) != '', 'murder of a victim with no hold backs no report'),
        (report_evidence('murder', 10.0, last_murder=9.5, violent=1000) != '', 'murder is refused when the violent bounty already holds 1000'),
        (report_evidence('assault', 10.0, struck=((9.5, False),)) == '', 'assault with a member struck today is taken'),
        (report_evidence('assault', 10.0, struck=((8.0, False), (-1.0, False))) != '', 'assault with nobody struck within a day is refused'),
        (report_evidence('assault', 10.0, struck=((9.8, True),)) != '', 'assault backed only by the guard or a teammate is refused'),
        (report_evidence('theft', 10.0) != '' and report_evidence('pickpocketing', 10.0) != '', 'theft and pickpocketing are never reported'),
        (free_clears(['persuade', 'persuade'], 100, 30) == 1 and free_clears(['persuade', 'persuade'], 100, 30, fixed=False) == 2,
         'waiver and persuade share one free clear a day per hold'),
        (free_clears(['persuade'], 20, 80, thane=False) == 0 and free_clears(['persuade'], 20, 80, thane=False, fixed=False) == 1,
         'persuade needs Speech of at least the bounty'),
        (quest_progress(False, True, 0) == 0, 'a quest running from the start of the game at stage 0 is not started'),
        (quest_progress(False, False, 20) == 2, 'a quest stopped after starting (a pointer quest) is over'),
        (quest_progress(False, True, 10) == 1 and quest_progress(True, False, 200) == 2, 'running with a stage is running, completed is done'),
        (told_events([('c00', True, []), ('c03', True, ['c00']), ('c06', True, ['c00', 'c03'])]) == ['c06'] and
         told_events([('c00', True, []), ('c03', True, ['c00']), ('c06', False, ['c00', 'c03'])]) == ['c03'],
         'only the newest rank of a guild is told as an event'),
        (gift_scored(1) == 0 and gift_scored(49) == 0 and gift_scored(50) == 0.5 and gift_scored(900) == 5.0, 'gold under 50 is no scored gift'),
        (report_evidence('trespassing', 10.0) == '' and report_evidence('lockpicking', 10.0) == '', '5-gold crimes need only the witness'),
        (waive_twice(True) == 1 and waive_twice(False) == 2, 'the Thane/fame waiver is given once a day per hold'),
        (dungeon_race(True) == 1 and dungeon_race(False) == 2, 'two interleaved location changes credit one cleared dungeon once'),
    ]
    fails = 0
    for ok, what in cases:
        print(('PASS' if ok else 'FAIL') + ' ' + what)
        fails += not ok
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=40)
    ap.add_argument('--steps', type=int, default=600)
    ap.add_argument('--original', action='store_true', help='only run the logic as it was before the fixes')
    ap.add_argument('-v', action='store_true')
    args = ap.parse_args()
    fails = 0

    def report(title, fixes):
        total, ops, calls, events, tokens, line, dropped = run_all(fixes, args.seeds, args.steps, args.v)
        print(f'== {title}: {args.seeds} seeds x {args.steps} steps, {sum(events.values())} events sent')
        print('   events: ' + ', '.join(f'{k[5:]} {v}' for k, v in sorted(events.items())))
        print(f'   stale tasks dropped after loads: {dropped}')
        print('   worst plugin operations per task beyond one pass over the loaded actors: ' + ', '.join(f'{k} {v}' for k, v in sorted(ops.items(), key=lambda kv: -kv[1])))
        print('   worst Papyrus storage calls per event: ' + ', '.join(f'{k[5:]} {v}' for k, v in sorted(calls.items(), key=lambda kv: -kv[1])))
        print(f'   most World fact tokens seen for one NPC: {tokens}; most Line() slots needed: {line} of 8')
        for k, v in sorted(total.items()):
            print(f'   {k}: {len(v)}' + (f'  e.g. {v[0]}' if v else ''))
        return total, ops

    if args.original:
        report('original logic', set())
        return 0
    total, ops = report('fixed logic', set(FIXES))
    bound = 80  # the 64-entry attacker cap plus a few map operations
    for k, v in sorted(total.items()):
        print(f'FAIL {k}: {len(v)} violations')
        for line in v[:5]:
            print('     ' + line)
        fails += 1
    worst = max(ops.values())
    print(('PASS' if worst <= bound else 'FAIL') + f' work per task bounded: one pass over the loaded actors + at most {worst} operations (bound {bound})')
    fails += worst > bound
    if not total:
        print('PASS attribution, rate limits, no leak across loads, counts in range, batching, join, Line() slots')

    old, _ = report('original logic (self test: each old defect must show)', set())
    seen = {BUG_OF[k] for k in old if k in BUG_OF}
    for fix, what in FIXES.items():
        ok = fix in seen
        print(('PASS' if ok else 'FAIL') + f' model sees the old defect: {what}')
        fails += not ok
    fails += evidence_checks()
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
