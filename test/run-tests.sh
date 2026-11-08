#!/usr/bin/env bash
# Drives the World module's live tests (F1-F6) over DevBench, then checks world.json on disk.
# Needs: the game running in a test profile with DevBench with a save loaded, this mod's test build (MLWW_Test.pex next
# to the module's scripts), the player in or near Whiterun/Riverwood, no helmet or hood on, not Thane of Whiterun or
# Haafingar yet (F1 and F3 make the player Thane of both: use a throwaway save).
# usage: bash run-tests.sh                      e.g. SOLITUDE_GUARD=0x000A1D2E bash run-tests.sh
#        SUITE=events bash run-tests.sh         only the E tests (game events as facts), see there
#   SOLITUDE_GUARD  a Solitude guard reference for the strangers test (default: Jarl Elisif, also Haafingar)
set -u
MO2=${MO2:?set MO2 to your Mod Organizer 2 instance folder}
WORLD="$MO2/overwrite/SKSE/Plugins/StorageUtilData/MantellaLivingWorld/world.json"
DB="$MO2/tools/devbench-cli.sh"
PASS=0; FAIL=0

call() { bash "$DB" call "$@" 2>&1 | py -3 -I -c "import json,sys
try:
    d=json.load(sys.stdin); print(d.get('returned') if d.get('called') else 'ERROR '+str(d))
except Exception: print('ERROR no reply')"; }
t() { call MLWW_Test "$1" "${2:-[]}"; }
con() { bash "$DB" exec "$1" >/dev/null 2>&1; }
note() { bash "$DB" notify "$1" >/dev/null 2>&1; echo "== $1"; }
check() {  # check <name> <value> <regex>
  if printf '%s' "$2" | grep -qiE -- "$3"; then PASS=$((PASS+1)); echo "   PASS $1"; else FAIL=$((FAIL+1)); echo "   FAIL $1: got [$2], want /$3/"; fi
}
world() {  # world <python expression over d>: evaluates against world.json, prints the result or ERROR
  py -3 -I -c "import json,sys
try:
    d=json.load(open(sys.argv[1],encoding='utf-8'))
except Exception as e:
    print('ERROR invalid json', e); sys.exit()
print($1)" "$WORLD"
}
f() { printf '{"form":"%s"}' "$1"; }
# A full refresh reads every quest row and takes far longer than one DevBench call may: wait for world.json to change.
refresh() {
  local before; before=$(stat -c %Y "$WORLD" 2>/dev/null || echo 0)
  t Refresh >/dev/null
  for _ in $(seq 1 90); do
    [ "$(stat -c %Y "$WORLD" 2>/dev/null || echo 0)" != "$before" ] && { sleep 1; echo "saved good=$(world "'true'")"; return; }
    sleep 1
  done
  echo "saved good=timeout"
}

LUCAN=$(f 0x13487); CAMILLA=$(f 0x13488); HOD=$(f 0x1348A); BELETHOR=$(f 0x1A672); ADRIANNE=$(f 0x1A67C)
PROVENTUS=$(f 0x1A67D); STRANGER=$(f "${SOLITUDE_GUARD:-0x198C1}")
WHITERUN=0

bash "$DB" alive | grep -qi running || { echo "game not running with a save loaded"; exit 2; }
con "set GameHour to 12"
# E1-E9 game events as facts: SUITE=events bash run-tests.sh (only this part runs). Needs a follower set as a teammate
# next to the player and a merchant. The rows send the plugin's own events; the "real" checks go through the engine.
#   FOLLOWER  the follower's reference (default Lydia, 0xA2C94)   MERCHANT  default Belethor
if [ "${SUITE:-}" = events ]; then
  NPC=$(f "${FOLLOWER:-0xA2C94}"); SHOP=$(f "${MERCHANT:-0x1A672}"); PLAYER=$(f 0x14)
  fact() { t Fact "[$1,\"$2\"]"; }
  ev() { t FakeEvent "[$1,\"$2\",\"$3\",$4]" >/dev/null; sleep 1; }  # the handler runs after the call returns
  note "E0 setup"
  check "follower is in the party" "$(t PartyNames)" "^[1-9]"
  t ForgetFacts "[$NPC]" >/dev/null; t ForgetFacts "[$SHOP]" >/dev/null
  check "no facts left after forgetting" "$(fact "$NPC" fact_saved)$(fact "$SHOP" fact_customer)" '^$'

  note "E1 rows: event; text; number; fact key; wanted value (sender: the follower)"
  while IFS=';' read -r name event text num key want; do
    [ -z "$name" ] && continue
    ev "$NPC" "$event" "$text" "$num"; t WriteFacts >/dev/null
    check "$name" "$(fact "$NPC" "$key")" "$want"
  done <<'ROWS'
healed by player once;MLWW_Healed;;1;fact_saved;^[0-9]+\|-1\|3\|With .+: heals 1 to you$
healed by player twice;MLWW_Healed;;1;fact_saved;: heals 2 to you$
follower healed player;MLWW_Healed;;0;fact_saved;: heals 2 to you, 1 to them$
saved by the player;MLWW_Saved;heal;1;fact_saved;: they saved you once; heals 2 to you, 1 to them$
saved the player;MLWW_Saved;kill;0;fact_saved;: they saved you once, you saved them once; heals
friendly fire by player;MLWW_FriendlyFire;;1;fact_saved;; hits 1 to you$
friendly fire on player;MLWW_FriendlyFire;;0;fact_saved;; hits 1 to you, 1 to them$
fought once;MLWW_Fought;;0;fact_fought;^[0-9]+\|-1\|2\|With .+: 1 fight$
fought twice;MLWW_Fought;;0;fact_fought;: 2 fights$
defended;MLWW_Defended;;0;fact_fought;: 2 fights, defended them in 1$
ROWS

  note "E2 kills and the strongest enemy (sender = killer)"
  ev "$NPC" MLWW_Kill "Bandit" 12; ev "$PLAYER" MLWW_Kill "Bandit Chief" 20; ev "$NPC" MLWW_Kill "Wolf" 3; t WriteFacts >/dev/null
  check "kill counts" "$(fact "$NPC" fact_fought)" "; kills you 2, them 1; "
  check "strongest by level" "$(fact "$NPC" fact_fought)" "; strongest enemy Bandit Chief \(level 20\)$"
  ev "$PLAYER" MLWW_Kill "Vilkas" 1015; t WriteFacts >/dev/null
  check "a unique outranks level, no level shown" "$(fact "$NPC" fact_fought)" "; strongest enemy Vilkas$"
  ev "$NPC" MLWW_Kill "Dragon" 2040; t WriteFacts >/dev/null
  check "a dragon outranks a unique" "$(fact "$NPC" fact_fought)" "; strongest enemy Dragon$"
  check "no player's strongest while the follower was there for it" "$(fact "$NPC" fact_fought)" "strongest enemy Dragon$"

  note "E3 good customer (Trade: number = player's gold change)"
  ev "$SHOP" MLWW_Trade "-1" -4987; ev "$SHOP" MLWW_Trade "-1" 30; t WriteFacts >/dev/null
  check "spent and sold, one visit" "$(fact "$SHOP" fact_customer)" "^-1\|-1\|1\|.+ spent ~5,000 gold, sold you ~30 in goods$"
  ev "$SHOP" MLWW_TradeGoods "Iron Dagger" 3; t WriteFacts >/dev/null
  check "what the player sells most" "$(fact "$SHOP" fact_customer)" ", mostly Iron Dagger$"

  note "E4 dungeon"
  check "dungeon stat raised" "$(t ClearDungeon '[1]')" "^cleared [0-9]+"
  check "dungeon fact" "$(fact "$NPC" fact_fought)" "; cleared "

  note "E5 save consistency: no numbers, no fact"
  t ForgetFacts "[$NPC]" >/dev/null
  check "facts removed with the numbers" "$(fact "$NPC" fact_saved)$(fact "$NPC" fact_fought)" '^$'

  note "E6 real heal: player casts Heal Other on the hurt follower"
  t Hurt "[$NPC,60]" >/dev/null; t CastAt "[77778,$PLAYER,$NPC]" >/dev/null; sleep 3; t WriteFacts >/dev/null
  check "real heal recorded" "$(fact "$NPC" fact_saved)" ": heals 1 to you$"

  note "E7 real kill: the follower kills a placed bandit"
  check "bandit placed and killed" "$(t SpawnKill "[113880,$NPC]")" "dead=True"
  sleep 2; t WriteFacts >/dev/null
  check "real kill counted" "$(fact "$NPC" fact_fought)" "kills you 1, "

  note "E8 real rescue: follower down, player heals within 15 s"
  check "follower in bleedout" "$(t Down "[$NPC,0]")" "bleeding=True"
  sleep 1; t CastAt "[77778,$PLAYER,$NPC]" >/dev/null; sleep 3; t WriteFacts >/dev/null
  check "rescue recorded" "$(fact "$NPC" fact_saved)" ": they saved you once"
  t Down "[$NPC,1]" >/dev/null

  t ForgetFacts "[$NPC]" >/dev/null; t ForgetFacts "[$SHOP]" >/dev/null
  note "event tests finished: $PASS passed, $FAIL failed"
  [ "$FAIL" -eq 0 ]; exit
fi
note "setup"
check "quests running" "$(t Status)" "state=true meetings=true recognition=true pairs=true crime=true"
check "old-save registration (as on load)" "$(t Reload)" "registered"
t EndConversation >/dev/null; t ClearSent >/dev/null; sleep 1
t GiveGold '[3000]' >/dev/null

note "F4 hiding and recognition (Belethor, observation 2 then 4)"
con "player.additem 10D6A6 1"; con "player.unequipitem 10D6A6"; sleep 1
t SetObservation "[$BELETHOR,2]" >/dev/null; t ForgetMet "[$BELETHOR]" >/dev/null
check "no hood: recognised" "[$(t Verdict "[$BELETHOR]")]" '^\[(None)?\]$'
con "player.equipitem 10D6A6"; sleep 1
check "hood, observation 2: not recognised" "$(t Verdict "[$BELETHOR]")" "does not recognise .*hood"
t Join "[$BELETHOR]" >/dev/null; sleep 2
check "hood line reaches Mantella on NPC added" "$(t LastSent)" "^recognition: .*does not recognise"
t EndConversation >/dev/null
t SetObservation "[$BELETHOR,4]" >/dev/null
check "hood, observation 4: sees through" "$(t Verdict "[$BELETHOR]")" "sees through"
t SetObservation "[$BELETHOR,2]" >/dev/null
con "player.unequipitem 10D6A6"

note "F5 who knows whom"
check "Lucan + Camilla: close" "$(t PairLevel "[$LUCAN,$CAMILLA]")" "^3$"
check "Riverwood local + Solitude: strangers" "$(t PairLevel "[$HOD,$STRANGER]")" "^0$"
check "two Whiterun merchants: know of" "$(t PairLevel "[$BELETHOR,$ADRIANNE]")" "^1$"
t ClearSent >/dev/null
t Join "[$LUCAN]" >/dev/null; t Join "[$CAMILLA]" >/dev/null; sleep 2
check "pair line on second NPC" "$(t LastSent)" "^pairs: .*(Lucan|Camilla).* know each other well"
check "one line per pair" "$(t SentCountOf '["pairs"]')" "^1$"
t EndConversation >/dev/null; sleep 1

note "F6 settle crime (Proventus, steward of Whiterun)"
t ResetPersuade "[$WHITERUN]" >/dev/null  # a save from an earlier run on the same game day
con "player.setav speechcraft 50"
t SetBounty "[$WHITERUN,40,0]" >/dev/null; g0=$(t Gold)
check "pay: line" "$(t Settle "[$PROVENTUS,\"pay\"]")" "paid the 40 gold bounty"
check "pay: bounty cleared" "$(t Bounty "[$WHITERUN]")" "^0/0$"
check "pay: 40 gold taken" "$(( g0 - $(t Gold) ))" "^40$"
t SetBounty "[$WHITERUN,30,1000]" >/dev/null
check "pay with murder: violent stays" "$(t Settle "[$PROVENTUS,\"pay\"]")" "1000 gold for violent crimes stands"
check "pay with murder: only non-violent cleared" "$(t Bounty "[$WHITERUN]")" "^0/1000$"
check "bribe cost at Speech 50, bounty 80" "$(t BribeCost '[80]')" "^100$"
t SetBounty "[$WHITERUN,80,0]" >/dev/null; g0=$(t Gold)
check "bribe: line" "$(t Settle "[$PROVENTUS,\"bribe\"]")" "took a 100 gold bribe"
check "bribe: cleared" "$(t Bounty "[$WHITERUN]")" "^0/0$"
check "bribe: 100 gold taken" "$(( g0 - $(t Gold) ))" "^100$"
con "player.setav speechcraft 70"  # persuading needs Speech at least the bounty
t ResetPersuade "[$WHITERUN]" >/dev/null; t SetBounty "[$WHITERUN,60,0]" >/dev/null; g0=$(t Gold)
check "persuade: let go" "$(t Settle "[$PROVENTUS,\"persuade\"]")" "let .* 60 gold bounty .* go"
check "persuade: cleared, free" "$(t Bounty "[$WHITERUN]") $(( g0 - $(t Gold) ))" "^0/0 0$"
t SetBounty "[$WHITERUN,60,0]" >/dev/null
check "second persuade same day refused" "$(t Settle "[$PROVENTUS,\"persuade\"]")" "already had a bounty let go"
check "second persuade: bounty kept" "$(t Bounty "[$WHITERUN]")" "^60/0$"
check "refusal sent as event line" "$(t LastSent)" "^crime: .*already had a bounty let go"
t ResetPersuade "[$WHITERUN]" >/dev/null; t SetBounty "[$WHITERUN,150,0]" >/dev/null
check "persuade over 100 refused" "$(t Settle "[$PROVENTUS,\"persuade\"]")" "too large to talk away"
t SetBounty "[$WHITERUN,0,1000]" >/dev/null
check "murder only: bribe refused" "$(t Settle "[$PROVENTUS,\"bribe\"]")" "violent crimes"
check "murder bounty untouched" "$(t Bounty "[$WHITERUN]")" "^0/1000$"
check "non-guard cannot settle" "$(t Settle "[$HOD,\"pay\"]")" "^Only a guard"
check "report without witness refused" "$(t ReportNoWitness "[$PROVENTUS,\"assault\"]")" "no witness"  # theft reports were removed
check "report refused: no bounty added" "$(t Bounty "[$WHITERUN]")" "^0/1000$"

note "F1 world state file"
t SetBounty "[$WHITERUN,40,15]" >/dev/null
check "refresh saved" "$(refresh)" "good=true"
check "world.json bounty Whiterun 55" "$(world "d['bounty']['Whiterun'], d['bounty_violent']['Whiterun']")" "55[^0-9]+15"
check "world.json has every key" "$(world "sorted(k for k in ['fame','bounty','war_side','thane','guilds','mq_stage','events'] if k not in d)")" '^\[\]$'
con "completequest Favor253"; sleep 2
check "refresh after thane stage" "$(refresh)" "good=true"
check "world.json: Thane of Whiterun" "$(world "'Whiterun' in d['thane']")" "^True$"
check "world.json: dated thane event" "$(world "[e['day'] for e in d['events'] if e['id']=='thane_whiterun']")" '^\[[0-9]'
check "world.json fame Whiterun counts thane" "$(world "d['fame']['Whiterun'] >= 2")" "^True$"

note "F3 since we last met (Lucan)"
t EndConversation >/dev/null; t ForgetMeeting "[$LUCAN]" >/dev/null; t ClearSent >/dev/null
t Join "[$LUCAN]" >/dev/null; sleep 2
check "first meeting: nothing" "$(t SentCountOf '["meetings"]')" "^0$"
t EndConversation >/dev/null
m0=$(t ThaneMask)
t SetBounty "[$WHITERUN,90,15]" >/dev/null; con "completequest Favor252"; sleep 2; refresh >/dev/null
m1=$(t ThaneMask)
t AgeMeeting "[$LUCAN,2.0]" >/dev/null
t Join "[$LUCAN]" >/dev/null; sleep 2
line=$(t LastSent)
check "next day: one line" "$(t SentCountOf '["meetings"]')" "^1$"
if [ "$m0" = "$m1" ]; then echo "   SKIP line lists the thane title (this save is already Thane of Haafingar)"; else check "line lists the thane title" "$line" "Thane of Haafingar"; fi
check "line lists the bounty" "$line" "bounty in Whiterun rose from 55 to 105"
t EndConversation >/dev/null
t Join "[$LUCAN]" >/dev/null; sleep 2
check "same day again: nothing new" "$(t SentCountOf '["meetings"]')" "^1$"
t EndConversation >/dev/null

note "F6 waive for a Thane"
t ResetPersuade "[$WHITERUN]" >/dev/null
t SetBounty "[$WHITERUN,30,0]" >/dev/null; g0=$(t Gold)
check "thane: minor bounty waived" "$(t Settle "[$PROVENTUS,\"pay\"]")" "waived .* Thane"
check "waive: free and cleared" "$(t Bounty "[$WHITERUN]") $(( g0 - $(t Gold) ))" "^0/0 0$"

t SetBounty "[$WHITERUN,0,0]" >/dev/null
check "world.json still valid at the end" "$(refresh) $(world "'ok'")" "good=true.*ok"
note "tests finished: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
