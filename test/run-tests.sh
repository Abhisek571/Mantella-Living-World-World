#!/usr/bin/env bash
# Drives the World module's live tests (F1-F6) over DevBench, then checks world.json on disk.
# Needs: the game running in a test profile with DevBench with a save loaded, this mod's test build (MLWW_Test.pex next
# to the module's scripts), the player in or near Whiterun/Riverwood, no helmet or hood on, not Thane of Whiterun or
# Haafingar yet (F1 and F3 make the player Thane of both: use a throwaway save).
# usage: bash run-tests.sh                      e.g. SOLITUDE_GUARD=0x000A1D2E bash run-tests.sh
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

LUCAN=$(f 0x13487); CAMILLA=$(f 0x13488); HOD=$(f 0x1348A); BELETHOR=$(f 0x1A672); ADRIANNE=$(f 0x1A67C)
PROVENTUS=$(f 0x1A67D); STRANGER=$(f "${SOLITUDE_GUARD:-0x198C1}")
WHITERUN=0

bash "$DB" alive | grep -qi running || { echo "game not running with a save loaded"; exit 2; }
con "set GameHour to 12"
note "setup"
check "quests running" "$(t Status)" "state=true meetings=true recognition=true pairs=true crime=true"
check "old-save registration (as on load)" "$(t Reload)" "registered"
t EndConversation >/dev/null; t ClearSent >/dev/null; sleep 1
t GiveGold '[3000]' >/dev/null

note "F4 hiding and recognition (Belethor, observation 2 then 4)"
con "player.additem 10D6A6 1"; con "player.unequipitem 10D6A6"; sleep 1
t SetObservation "[$BELETHOR,2]" >/dev/null
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
t ResetPersuade "[$WHITERUN]" >/dev/null; t SetBounty "[$WHITERUN,60,0]" >/dev/null; g0=$(t Gold)
check "persuade: let go" "$(t Settle "[$PROVENTUS,\"persuade\"]")" "let .* 60 gold bounty .* go"
check "persuade: cleared, free" "$(t Bounty "[$WHITERUN]") $(( g0 - $(t Gold) ))" "^0/0 0$"
t SetBounty "[$WHITERUN,60,0]" >/dev/null
check "second persuade same day refused" "$(t Settle "[$PROVENTUS,\"persuade\"]")" "already talked a bounty away"
check "second persuade: bounty kept" "$(t Bounty "[$WHITERUN]")" "^60/0$"
check "refusal sent as event line" "$(t LastSent)" "^crime: .*already talked"
t ResetPersuade "[$WHITERUN]" >/dev/null; t SetBounty "[$WHITERUN,150,0]" >/dev/null
check "persuade over 100 refused" "$(t Settle "[$PROVENTUS,\"persuade\"]")" "too large to talk away"
t SetBounty "[$WHITERUN,0,1000]" >/dev/null
check "murder only: bribe refused" "$(t Settle "[$PROVENTUS,\"bribe\"]")" "violent crimes"
check "murder bounty untouched" "$(t Bounty "[$WHITERUN]")" "^0/1000$"
check "non-guard cannot settle" "$(t Settle "[$HOD,\"pay\"]")" "^Only a guard"
check "report without witness refused" "$(t ReportNoWitness "[$PROVENTUS,\"theft\"]")" "no witness"
check "report refused: no bounty added" "$(t Bounty "[$WHITERUN]")" "^0/1000$"

note "F1 world state file"
t SetBounty "[$WHITERUN,40,15]" >/dev/null
check "refresh saved" "$(t Refresh)" "good=true"
check "world.json bounty Whiterun 55" "$(world "d['bounty']['Whiterun'], d['bounty_violent']['Whiterun']")" "55[^0-9]+15"
check "world.json has every key" "$(world "sorted(k for k in ['fame','bounty','war_side','thane','guilds','mq_stage','events'] if k not in d)")" '^\[\]$'
con "completequest Favor253"; sleep 2
check "refresh after thane stage" "$(t Refresh)" "good=true"
check "world.json: Thane of Whiterun" "$(world "'Whiterun' in d['thane']")" "^True$"
check "world.json: dated thane event" "$(world "[e['day'] for e in d['events'] if e['id']=='thane_whiterun']")" '^\[[0-9]'
check "world.json fame Whiterun counts thane" "$(world "d['fame']['Whiterun'] >= 2")" "^True$"

note "F3 since we last met (Lucan)"
t EndConversation >/dev/null; t ForgetMeeting "[$LUCAN]" >/dev/null; t ClearSent >/dev/null
t Join "[$LUCAN]" >/dev/null; sleep 2
check "first meeting: nothing" "$(t SentCountOf '["meetings"]')" "^0$"
t EndConversation >/dev/null
t SetBounty "[$WHITERUN,90,15]" >/dev/null; con "completequest Favor252"; sleep 2; t Refresh >/dev/null
t AgeMeeting "[$LUCAN,2.0]" >/dev/null
t Join "[$LUCAN]" >/dev/null; sleep 2
line=$(t LastSent)
check "next day: one line" "$(t SentCountOf '["meetings"]')" "^1$"
check "line lists the thane title" "$line" "Thane of Haafingar"
check "line lists the bounty" "$line" "bounty in Whiterun rose from 55 to 105"
t EndConversation >/dev/null
t Join "[$LUCAN]" >/dev/null; sleep 2
check "same day again: nothing new" "$(t SentCountOf '["meetings"]')" "^1$"
t EndConversation >/dev/null

note "F6 waive for a Thane"
t SetBounty "[$WHITERUN,30,0]" >/dev/null; g0=$(t Gold)
check "thane: minor bounty waived" "$(t Settle "[$PROVENTUS,\"pay\"]")" "waived .* Thane"
check "waive: free and cleared" "$(t Bounty "[$WHITERUN]") $(( g0 - $(t Gold) ))" "^0/0 0$"

t SetBounty "[$WHITERUN,0,0]" >/dev/null
check "world.json still valid at the end" "$(t Refresh) $(world "'ok'")" "good=true.*ok"
note "tests finished: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
