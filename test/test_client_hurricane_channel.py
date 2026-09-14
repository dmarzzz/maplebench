"""Compile the pinned Stage dispatch, retaining ordinary held-action behavior."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test/fixtures/client-hurricane-channel/Gameplay/Stage.cpp"
STAGE_SHA256 = "9eb05190e3fb802a4953a5f38297a60d35b42dd77b23f46bab97b37d467b36bf"


def method(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


DECLARATIONS = r"""
#include <cassert>
#include <chrono>
#include <cstdint>
#include <vector>
#include <utility>
#include <unordered_map>
namespace jrc {
struct KeyType { enum Id {ACTION,SKILL,ITEM,FACE,MENU}; };
struct KeyAction {
    enum Id {SIT,ATTACK,PICKUP,JUMP,LEFT,RIGHT};
    static Id actionbyid(int32_t value) { return static_cast<Id>(value); }
};
struct Player {
    std::unordered_map<int,bool> held;
    int items=0, expressions=0;
    bool is_key_down(KeyAction::Id key) const {
        auto found=held.find(key); return found!=held.end() && found->second;
    }
    void use_item(int32_t) { ++items; }
    void set_expression(int32_t) { ++expressions; }
};
struct Playable {
    Player& player;
    std::vector<std::pair<int,bool>> actions;
    explicit Playable(Player& value): player(value) {}
    void send_action(KeyAction::Id key, bool down) {
        actions.emplace_back(key,down); player.held[key]=down;
    }
};
struct Combat {
    std::vector<int32_t> attempts;
    std::vector<int32_t> executed;
    bool permitted=true;
    void cancel_channel() {}
    void send_skill_key(int32_t id, bool down) { if (down) use_move(id); }
    void use_move(int32_t id) {
        attempts.push_back(id);
        if (permitted) executed.push_back(id);
    }
};
struct Stage {
    enum State {INACTIVE,TRANSITION,ACTIVE};
    State state=ACTIVE;
    Player player;
    Playable actor{player};
    Playable* playable=&actor;
    Combat combat;
    bool intro_locked=false;
    int seats=0, drops=0;
    uint64_t last_pickup_time=0;
    static constexpr uint64_t PICKUP_INTERVAL_MS=100;
    std::vector<std::pair<int,bool>> directions;
    bool is_intro_input_locked() const { return intro_locked; }
    void handle_directional_context(KeyAction::Id id,bool down) {
        directions.emplace_back(id,down);
    }
    void check_seats() { ++seats; }
    void check_drops() { ++drops; }
    void send_key(KeyType::Id,int32_t,bool);
    void handle_held_actions();
};
"""


CHECKS = r"""
}
int main() {
    using namespace jrc;
    // The controller releases every key at the timed endpoint and again in its
    // final cleanup. Neither a matching nor an unmatched keyup may start a move.
    for (int id : {3121004,3111004,2221006,3101004,3121002,2001002,2201001}) {
        Stage stage;
        stage.send_key(KeyType::SKILL,id,true);
        stage.send_key(KeyType::SKILL,id,false);
        stage.send_key(KeyType::SKILL,id,false);
        assert(stage.combat.attempts.size()==(FIXED ? 1u : 3u));
        assert(stage.combat.executed.size()==(FIXED ? 1u : 3u));
        assert(stage.combat.attempts.front()==id);
        Stage unmatched;
        unmatched.send_key(KeyType::SKILL,id,false);
        assert(unmatched.combat.attempts.size()==(FIXED ? 0u : 1u));
    }
    // Ending a held skill while another attack finishes cannot turn release
    // into a new cast, even when the original keydown was denied by Combat.
    Stage denied;
    denied.combat.permitted=false;
    denied.send_key(KeyType::SKILL,3121004,true);
    assert(denied.combat.executed.empty());
    denied.combat.permitted=true;
    denied.send_key(KeyType::SKILL,3121004,false);
    assert(denied.combat.executed.size()==(FIXED ? 0u : 1u));
    denied.send_key(KeyType::SKILL,3121004,true);
    assert(denied.combat.executed.size()==(FIXED ? 1u : 2u));

    // Ordinary browser keydown repeat remains unchanged by this bounded patch.
    // A future channel state machine must deal with repeat separately.
    Stage repeated;
    repeated.send_key(KeyType::SKILL,3121004,true);
    repeated.send_key(KeyType::SKILL,3121004,true);
    assert(repeated.combat.attempts.size()==2);
    for (int i=0;i<10;++i) repeated.handle_held_actions();
    assert(repeated.combat.attempts.size()==2); // not a channel implementation

    // Basic attack repeats belong to the existing fixed update loop. Repeated
    // keydown does not add an immediate attack; keyup ends those normal repeats.
    Stage basic;
    basic.send_key(KeyType::ACTION,KeyAction::ATTACK,true);
    basic.send_key(KeyType::ACTION,KeyAction::ATTACK,true);
    assert(basic.combat.attempts.size()==1);
    basic.handle_held_actions(); basic.handle_held_actions();
    assert(basic.combat.attempts.size()==3);
    basic.send_key(KeyType::ACTION,KeyAction::ATTACK,false);
    basic.send_key(KeyType::ACTION,KeyAction::ATTACK,false);
    basic.handle_held_actions();
    assert(basic.combat.attempts.size()==3);
    for (int id:basic.combat.attempts) assert(id==0);

    Stage movement;
    movement.send_key(KeyType::ACTION,KeyAction::LEFT,true);
    movement.send_key(KeyType::ACTION,KeyAction::LEFT,false);
    assert(movement.actor.actions.size()==2);
    assert(movement.directions==movement.actor.actions);
    assert(!movement.player.is_key_down(KeyAction::LEFT));
    movement.send_key(KeyType::ACTION,KeyAction::JUMP,true);
    movement.handle_held_actions();
    assert(movement.actor.actions.back()==std::make_pair(int(KeyAction::JUMP),true));
    movement.send_key(KeyType::ACTION,KeyAction::JUMP,false);
    auto count=movement.actor.actions.size(); movement.handle_held_actions();
    assert(movement.actor.actions.size()==count);
    movement.send_key(KeyType::ACTION,KeyAction::SIT,true);
    movement.send_key(KeyType::ACTION,KeyAction::SIT,false);
    assert(movement.seats==1);

    // Preserve existing item/face dispatch; this patch changes only SKILL.
    Stage other;
    other.send_key(KeyType::ITEM,2000000,true);
    other.send_key(KeyType::ITEM,2000000,false);
    other.send_key(KeyType::FACE,1,true);
    other.send_key(KeyType::FACE,1,false);
    assert(other.player.items==2 && other.player.expressions==2);
    for (int mode=0;mode<3;++mode) {
        Stage blocked;
        if (mode==0) blocked.state=Stage::INACTIVE;
        if (mode==1) blocked.playable=nullptr;
        if (mode==2) blocked.intro_locked=true;
        blocked.send_key(KeyType::SKILL,3121004,true);
        blocked.send_key(KeyType::SKILL,3121004,false);
        assert(blocked.combat.attempts.empty());
    }
}
"""


class SkillKeyReleaseTest(unittest.TestCase):
    def test_real_stage_key_release_and_ordinary_action_paths(self):
        compiler = shutil.which("c++")
        if compiler is None:
            self.skipTest("C++ compiler required")
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), STAGE_SHA256)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "src/client/Gameplay/Stage.cpp"
            destination.parent.mkdir(parents=True)
            shutil.copytree(FIXTURE.parents[1], root / "src/client", dirs_exist_ok=True)
            subprocess.run(
                ["patch", "-p1", "--batch", "-i", str(ROOT / "patches/full-client/0018-hurricane-channel.patch")],
                cwd=root, check=True, capture_output=True, timeout=5,
            )
            for fixed, path in [(False, FIXTURE), (True, destination)]:
                with self.subTest(patched=fixed):
                    source = path.read_text()
                    methods = "\n".join(method(source, name) for name in (
                        "void Stage::send_key", "void Stage::handle_held_actions"))
                    program = root / "stage-test.cpp"
                    program.write_text(DECLARATIONS + methods + CHECKS.replace("FIXED", "true" if fixed else "false"))
                    compiled = subprocess.run(
                        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", str(program), "-o", str(root / "stage-test")],
                        capture_output=True, timeout=20, text=True,
                    )
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)
                    subprocess.run([str(root / "stage-test")], check=True, capture_output=True, timeout=5)
