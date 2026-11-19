"""Writes the World module's plugin as Spriggit YAML (one quest per job, each with a player alias that re-registers
its events on every game load) and its Mantella action files. Run from the project root."""
import json, os

E = 'Mantella Living World - World.esp'
# form id, editor id, script, name, needs the State quest
QUESTS = [
    ('000800', 'MLWW_QuestState', 'MLWW_State', 'Mantella Living World - World state', False),
    ('000801', 'MLWW_QuestMeetings', 'MLWW_Meetings', 'Mantella Living World - World meetings', True),
    ('000802', 'MLWW_QuestRecognition', 'MLWW_Recognition', 'Mantella Living World - World recognition', True),
    ('000803', 'MLWW_QuestPairs', 'MLWW_Pairs', 'Mantella Living World - World pairs', True),
    ('000804', 'MLWW_QuestCrime', 'MLWW_Crime', 'Mantella Living World - World crime', True),
    ('000805', 'MLWW_QuestBanter', 'MLWW_Banter', 'Mantella Living World - World banter', False),
    ('000806', 'MLWW_QuestInitiative', 'MLWW_Initiative', 'Mantella Living World - World initiative', False),
    ('000807', 'MLWW_QuestPersonal', 'MLWW_Personal', 'Mantella Living World - World personal', False),
    ('000808', 'MLWW_QuestTrade', 'MLWW_Trade', 'Mantella Living World - World trade', False),
]
# Settings (World page of the Integration Hub's MCM): form id, editor id, type, value, the script that uses it
GLOBALS = [('000810', 'MLWW_BanterOn', 'GlobalShort', 1, 'MLWW_Banter'),
           ('000811', 'MLWW_BanterChance', 'GlobalShort', 30, 'MLWW_Banter'),
           ('000812', 'MLWW_InitiativeOn', 'GlobalShort', 1, 'MLWW_Initiative'),
           # battle accounts: read by the SKSE plugin, no script
           ('000813', 'MLWW_BattleOn', 'GlobalShort', 1, None),
           ('000814', 'MLWW_BattleBystanders', 'GlobalShort', 0, None),
           ('000815', 'MLWW_BattleHours', 'GlobalShort', 6, None)]
STATE = QUESTS[0][0]


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def script_property(name, form_key):
    return f'    - MutagenObjectType: ScriptObjectProperty\n      Name: {name}\n      Object: {form_key}\n'


def quest_yaml(fid, eid, script, name, needs_state):
    alias = 'MLWW_BanterAlias' if script == 'MLWW_Banter' else 'MLWW_PlayerAlias'  # only banter needs OnHit
    props = script_property('PlayerRef', '000014:Skyrim.esm')
    if needs_state:
        props += script_property('World', f'{STATE}:{E}')
    props += ''.join(script_property(gname, f'{gfid}:{E}') for gfid, gname, _, _, user in GLOBALS if user == script)
    return (f"FormKey: {fid}:{E}\nEditorID: {eid}\nVirtualMachineAdapter:\n  Scripts:\n  - Name: {script}\n    Properties:\n{props}"
            f"  FileName: ''\n  Aliases:\n  - Property:\n      Name: ''\n      Object: {fid}:{E}\n      Alias: 0\n"
            f"    Scripts:\n    - Name: {alias}\n"
            f"Name:\n  TargetLanguage: English\n  Value: {name}\nFlags:\n- StartGameEnabled\nNextAliasID: 1\n"
            f"Aliases:\n- Name: PlayerAlias\n  Flags: []\n  ForcedReference: 000014:Skyrim.esm\n  VoiceTypes: Null\n")


def write_plugin():
    for fid, eid, script, name, needs_state in QUESTS:
        write(f'esp/Quests/{eid} - {fid}_{E}.yaml', quest_yaml(fid, eid, script, name, needs_state))
    for gfid, gname, typ, val, _ in GLOBALS:
        write(f'esp/Globals/{gname} - {gfid}_{E}.yaml', f'MutagenObjectType: {typ}\nFormKey: {gfid}:{E}\nEditorID: {gname}\nData: {val}\n')
    write('esp/RecordData.yaml', f'ModKey: {E}\nGameRelease: SkyrimSE\nModHeader:\n  Flags:\n  - Small\n  Author: itsPigeon2000\n'
          '  Description: Mantella Living World - World. Fame, crime, war side, quest outcomes, since we last met, hiding, who knows whom, settle crime, banter, NPCs who come to talk, what the player did to each NPC, battle accounts, trading by talk.\n'
          '  MasterReferences:\n  - Master: Skyrim.esm\n    FileSize: 0\n')
    write('esp/spriggit-meta.json', json.dumps({'PackageName': 'Spriggit.Yaml.Skyrim', 'Version': '0.40.0', 'Release': 'SkyrimSE', 'ModKey': E}, indent=2))

SETTLE_NOTE = "Needs Mantella Living World - World. Guards, stewards and Jarls only. Every way of settling asks you Yes/No first (letting a bounty go hands over any stolen goods). Bribe and persuade need Advanced Actions on in Mantella. Keep Mantella's own AbsolveCrime off."
REPORT_NOTE = "Needs Mantella Living World - World and Advanced Actions on in Mantella. Guards, stewards and Jarls only. A guard adds a bounty only when another NPC (not one of your followers) is present as a witness, once per crime per talk and at most the vanilla bounty per crime per hold each day. This is a separate action from Mantella's own ReportCrime, which you can keep off."
TRADE_NOTE = ("Needs Mantella Living World - World and Advanced Actions on in Mantella (it names the amount or the item). "
              "Followers, friends and lovers give and take freely; a stranger hands over gold or goods only as payment for what "
              "you handed them in the same talk. Anything you hand over asks you Yes/No first.")
AMOUNT = {'type': 'integer', 'minimum': 1, 'maximum': 100000}
ITEM = {'type': 'string', 'description': 'Item name, for the item kinds.'}
COUNT = {'type': 'integer', 'minimum': 1, 'maximum': 1000, 'description': 'How many; default 1.'}
ACTIONS = [
    {'identifier': 'mantella_mlww_settle_crime', 'name': 'SettleCrime', 'note': SETTLE_NOTE, 'lw_gate': 'authority',
     'description': "Settle the player's non-violent bounty in your hold: pay it, take a bribe, or let it go when persuaded.",
     'parameters': {'method': {'type': 'string', 'enum': ['pay', 'bribe', 'persuade'],
                               'description': 'pay: the player pays the bounty; bribe: the player pays you extra to forget it; persuade: you let a minor bounty go.'}},
     'required': ['method'],
     'one-on-one': True,
     'prompt': "If you are a guard, steward or Jarl and agree to settle the player's bounty (paid, bribed or persuaded), begin your response with '{key}:'"},
    # Not "ReportCrime": Mantella's Disabled Actions matches by name, and its own ReportCrime is disabled by default.
    {'identifier': 'mantella_mlww_report_crime', 'name': 'ReportWitnessedCrime', 'note': REPORT_NOTE, 'lw_gate': 'authority',
     'description': 'Add a bounty for a crime a witness in this conversation saw the player commit.',
     'parameters': {'crime': {'type': 'string', 'enum': ['trespassing', 'lockpicking', 'assault', 'murder'],
                              'description': 'The crime the witness saw.'}},
     'required': ['crime'],
     # The witness must be another NPC in the talk, so a one-on-one talk can never use it.
     'one-on-one': False,
     'prompt': "If you are a guard, steward or Jarl and someone here tells you they saw the player commit a crime, begin your response with '{key}:'"},
    # Trading by talk (MLWW_Trade): one action, the kind of trade inside. The Hub keeps only the first sentence of the
    # description (the action has no gate), so that sentence holds the stranger rule.
    {'identifier': 'mantella_mlww_trade', 'name': 'Trade', 'note': TRADE_NOTE + " offer_trade is for merchants only.",
     'description': "Moves real gold or goods: a merchant sells a ware the player asks to buy by name with offer_trade, at the shop price unless another was agreed (Barter only opens the shop menu to browse); a stranger pays only for what the player handed over first.",
     # live test 14: "a named item at the agreed price" lost "from their wares", and with "you give only what you carry"
     # Lucan refused a potion his chest held ("not among what I'm carrying"); OfferTrade takes no price as the shop price
     # live test 15: "once agreed ... a price agreed in talk" kept a plain "I'd like to buy X" (no price) on Barter
     'parameters': {'kind': {'type': 'string', 'enum': ['give_gold', 'ask_gold', 'give_item', 'ask_item', 'offer_trade', 'take_gift'],
                             'description': 'give_*: you hand over what you carry; ask_*: the player hands it to you; '
                                            'offer_trade: a merchant sells a ware asked for from the shop; take_gift: opens the gift menu.'},
                    'amount': dict(AMOUNT, description='Gold, for give_gold and ask_gold.'),
                    'item': ITEM, 'count': COUNT,
                    'price': dict(AMOUNT, description='offer_trade: the agreed gold for all of it; leave out for the shop price.')},
     'required': ['kind'],
     # Without arguments (Advanced Actions off) only the gift menu can be opened, as TakeGift did.
     'prompt': "When the player wants to give you something, begin your response with '{key}:'"},
]
# trades may follow each other (two items, a lower amount after a refusal); a crime is settled or reported once
NO_REPEAT = {'mantella_mlww_settle_crime', 'mantella_mlww_report_crime'}


def action_json(action):
    """One Mantella action file's content."""
    data = {'identifier': action['identifier'], 'name': action['name'], 'description': action['description'],
            'note': action['note'], 'key': action['name'], 'enabled': True}
    if action.get('lw_gate'):
        data['lw_gate'] = action['lw_gate']
    data.update({'parameters': action['parameters'], 'required': action['required'], 'prompt': action['prompt'],
                 'allowed_games': ['skyrim'], 'requires_response': True, 'is-interrupting': False,
                 'allow_repeat': action['identifier'] not in NO_REPEAT,
                 'one-on-one': action.get('one-on-one', True), 'multi-npc': True, 'radiant': False})
    return json.dumps(data, indent=4) + '\n'


def main():
    write_plugin()
    for action in ACTIONS:
        write(f"SKSE/Plugins/MantellaSoftware/data/actions/{action['identifier']}.json", action_json(action))
    print('world records written:', len(QUESTS), 'quests,', len(ACTIONS), 'actions')


if __name__ == '__main__':
    main()
