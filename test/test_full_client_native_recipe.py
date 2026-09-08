"""Execute the fixed recipe against an explicit fake SDK; never contact a game."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from full_client_native import contract, program


@unittest.skipUnless(shutil.which('node'), 'Node is required for fixed recipe execution')
class NativeRecipeTests(unittest.TestCase):
    def execute(self, class_id, *, stuck=False, elevated=False):
        code = program(contract(class_id, 'a' * 64))
        fixture = """
const code=CODE,stuck=STUCK,elevated=ELEVATED;
let now=0,requests=0;
const character={x:0,y:100,hp:100,mp:100,exp:0,level:180,alive:true};
const monsters=[{objectId:1,x:450,y:elevated?300:100}];
const events=[],observe=()=>({ready:true,character:{...character},monsters});
const sdk={
 async observe(){requests++;const result=observe();events.push({kind:'observe',at:now,result});return result;},
 async wait(ms){requests++;events.push({kind:'wait',at:now,ms});now+=ms;character.y=100;return{waitedMs:ms};},
 async pressKeys(keys,ms){requests++;events.push({kind:'input',at:now,keys,ms});now+=ms;
  if(keys[0]==='JUMP')character.y=70;
  if(!stuck&&keys[0]==='RIGHT')character.x+=ms/5;
  if(!stuck&&keys[0]==='LEFT')character.x-=ms/5;
  return{accepted:true,observation:observe()};}
};
(new Function('sdk','return (async()=>{'+code+'})()'))(sdk)
 .then(()=>process.stdout.write(JSON.stringify({events,requests,elapsed:now})))
 .catch(error=>{console.error(error);process.exitCode=1;});
""".replace('CODE', json.dumps(code)).replace('STUCK', str(stuck).lower()).replace('ELEVATED', str(elevated).lower())
        result = subprocess.run([shutil.which('node'), '--max-old-space-size=64', '-e', fixture],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_jump_precedes_every_skill_and_has_an_immediate_position_observation(self):
        result = self.execute('hero')
        events = result['events']
        index = next(i for i, event in enumerate(events) if event['kind'] == 'input')
        jump = events[index]
        self.assertEqual(jump['keys'], ['JUMP'])
        self.assertEqual(jump['ms'], 300)
        self.assertEqual(events[index - 1]['kind'], 'observe')
        self.assertEqual(events[index + 1]['kind'], 'observe')
        self.assertEqual(events[index - 1]['result']['character']['y'], 100)
        self.assertEqual(events[index + 1]['result']['character']['y'], 70)

    def test_each_class_keeps_animation_cooldowns_and_all_finite_budgets(self):
        for class_id in ('hero', 'bowmaster', 'ice_lightning_arch_mage'):
            with self.subTest(class_id=class_id):
                result = self.execute(class_id, stuck=True)
                actions = [x for x in result['events'] if x['kind'] == 'input']
                movement = [x for x in actions if x['keys'][0] in ('LEFT', 'RIGHT')]
                self.assertEqual(len(movement), 4)
                self.assertTrue(all(x['ms'] <= 1500 for x in movement))
                self.assertLessEqual(len(actions), 12)
                self.assertLessEqual(result['requests'], 100)
                self.assertLess(result['elapsed'], 30000)
                for earlier, later in zip(actions, actions[1:]):
                    if earlier['keys'][0] not in ('LEFT', 'RIGHT'):
                        self.assertGreaterEqual(later['at'] - earlier['at'] - earlier['ms'], 1000)

    def test_approach_reobserves_positions_and_stops_in_range(self):
        result = self.execute('hero')
        movements = [(i, e) for i, e in enumerate(result['events'])
                     if e['kind'] == 'input' and e['keys'][0] in ('LEFT', 'RIGHT')]
        self.assertLessEqual(len(movements), 4)
        self.assertEqual(movements[-1][1]['ms'], 30)
        for index, movement in movements:
            self.assertEqual(result['events'][index - 1]['kind'], 'observe')
            self.assertEqual(result['events'][index + 1]['kind'], 'observe')
        self.assertFalse([e for e in self.execute('hero', elevated=True)['events']
                          if e['kind'] == 'input' and e['keys'][0] in ('LEFT', 'RIGHT')])

    def test_bow_buffs_before_any_ranged_or_basic_attack(self):
        actions = [e['keys'][0] for e in self.execute('bowmaster')['events'] if e['kind'] == 'input']
        for attack in ('ATTACK', 'PRIMARY_SKILL', 'SECONDARY_SKILL'):
            self.assertLess(actions.index('BUFF_1'), actions.index(attack))
        self.assertNotIn('BRANDISH', actions)


if __name__ == '__main__':
    unittest.main()
