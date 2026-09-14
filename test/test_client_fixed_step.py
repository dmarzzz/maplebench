"""Compile the shipped WASM main_tick before/after the catch-up repair.

The production loop and timestep are real. Timer input, rendering and game
updates are inert counters. These tests do not establish live client speed.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'test/fixtures/client-fixed-step'
PATCH = ROOT / 'patches/full-client/0014-fixed-step-catch-up.patch'

STUBS = r'''
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <string>
#include "Constants.h"
static int64_t elapsed_input = 0;
static int64_t update_count = 0;
static int draw_count = 0, cancel_count = 0, close_count = 0;
static bool connected = true;
static int measured_updates = -1;
static double measured_wall = -1, measured_simulation = -1, measured_pending = -1;
static std::string emitted_code;
// Keep a named first argument: unlike a variadic no-op, this detects unescaped
// object-literal commas that split an EM_ASM code argument in the preprocessor.
#define EM_ASM(code, ...) emit_timing(#code, __VA_ARGS__)
void emit_timing(const char* code, int step, int maximum, int updates,
                 double elapsed, double wall, double simulation, double pending) {
    if (step != 8 || maximum != 128 || elapsed != elapsed_input / 1000.0) abort();
    emitted_code = code; measured_updates = updates;
    measured_wall = wall; measured_simulation = simulation; measured_pending = pending;
}
void emscripten_cancel_main_loop() { ++cancel_count; }
namespace jrc {
struct Timer {
    static Timer& get() { static Timer timer; return timer; }
    int64_t stop() { return elapsed_input; }
};
namespace Sound { void close() { ++close_count; } }
bool running() { return connected; }
void update() { ++update_count; }
void draw(float alpha) {
    if (alpha < 0 || alpha > 1) abort();
    ++draw_count;
}
'''

MAIN = r'''
}
int main(int argc, char** argv) {
    if (argc > 1 && std::string(argv[1]) == "emit") {
        elapsed_input = 115000; jrc::main_tick();
        std::cout << emitted_code; return 0;
    }
    while (std::cin >> elapsed_input) {
        if (elapsed_input < 0) connected = false;
        auto before = update_count;
        jrc::main_tick();
        std::cout << "[" << update_count - before << "," << update_count
                  << "," << jrc::accumulator << "," << draw_count
                  << "," << cancel_count << "," << close_count
                  << "," << measured_updates << "," << measured_wall
                  << "," << measured_simulation << "," << measured_pending << "]\n";
    }
}
'''


def loop_source(source):
    start = source.index('    static int64_t timestep =')
    return source[start:source.index('\n#endif', start)]


def compile_loop(directory, source, name):
    cpp = directory / (name + '.cpp')
    cpp.write_text(STUBS + loop_source(source) + MAIN)
    binary = directory / name
    subprocess.run([shutil.which('c++'), '-std=c++17', '-O0', '-I', str(FIXTURES),
                    str(cpp), '-o', str(binary)], check=True, capture_output=True, timeout=30)
    return binary


class FixedStepRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which('c++') or not shutil.which('patch'):
            raise unittest.SkipTest('C++ compiler and patch are required')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.tmp.name)
        source = cls.directory / 'src/client'
        source.mkdir(parents=True)
        for name in ('Journey.cpp', 'Timer.h'):
            shutil.copyfile(FIXTURES / name, source / name)
        cls.original = (source / 'Journey.cpp').read_text()
        subprocess.run(['patch', '-p1', '--batch', '--fuzz=0', '-i', str(PATCH)],
                       cwd=cls.directory, check=True, capture_output=True, timeout=10)
        cls.patched = (source / 'Journey.cpp').read_text()
        cls.before = compile_loop(cls.directory, cls.original, 'before')
        cls.after = compile_loop(cls.directory, cls.patched, 'after')

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def trace(self, binary, intervals):
        result = subprocess.run([str(binary)], input='\n'.join(map(str, intervals)),
                                text=True, capture_output=True, check=True, timeout=10)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def test_fixture_bytes_match_measured_build(self):
        expected = {
            'Journey.cpp': '0d65afcd456e62b8cf13aa082afa5a61d41a6978c540887610da93fa09747565',
            'Constants.h': 'af30de7af6681325ed5c677af121c311ee09a5303e676f9ccd267af4f9f27953',
            'Timer.h': 'e83e1dfe12b2f1f505b028a946f18486c133a503a1ff77f1c0865a001032b1aa',
        }
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest(), digest)

    def test_reproduces_slow_motion_at_measured_cadence(self):
        intervals = [115000] * 1000
        old = self.trace(self.before, intervals)[-1]
        new = self.trace(self.after, intervals)[-1]
        self.assertEqual(old[1] * 8000, 64000000)
        self.assertLess(old[1] * 8000 / sum(intervals), .56)
        self.assertEqual(new[1] * 8000 + new[2], sum(intervals) + 8000)
        self.assertLess(new[2], 8000)

    def test_preserves_fast_frame_behavior_without_acceleration(self):
        intervals = [16667] * 600
        self.assertEqual([r[:6] for r in self.trace(self.before, intervals)],
                         [r[:6] for r in self.trace(self.after, intervals)])

    def test_catches_up_each_supported_capture_gap(self):
        for interval in (8000, 33000, 115000, 499000, 1000000):
            with self.subTest(interval=interval):
                rows = self.trace(self.after, [interval] * 10)
                for i, row in enumerate(rows):
                    self.assertLessEqual(row[0], 128)
                    self.assertLess(row[2], 8000)
                    self.assertEqual(row[1] * 8000 + row[2], (i + 1) * interval + 8000)

    def test_overload_stays_bounded_and_retains_debt(self):
        rows = self.trace(self.after, [3000000, 16667, 16667, 16667])
        self.assertEqual(rows[0][0], 128)
        self.assertEqual(rows[0][2], 1984000)
        self.assertLess(rows[-1][2], 8000)
        self.assertEqual(rows[-1][1] * 8000 + rows[-1][2], 3058001)

    def test_telemetry_reports_actual_steps_wall_and_debt(self):
        rows = self.trace(self.after, [115000, 3000000, 16667])
        wall = 0
        for interval, row in zip([115000, 3000000, 16667], rows):
            wall += interval
            self.assertEqual(row[6], row[0])
            self.assertAlmostEqual(row[7], wall / 1000, places=2)
            self.assertAlmostEqual(row[8], row[1] * 8, places=2)
            self.assertAlmostEqual(row[9], row[2] / 1000, places=2)

    def test_disconnect_stops_without_extra_update_or_draw(self):
        row = self.trace(self.after, [-1])[0]
        self.assertEqual(row[:6], [0, 0, 8000, 0, 1, 1])

    def test_emitted_javascript_has_complete_macro_argument(self):
        if not shutil.which('node'):
            self.skipTest('Node required for actual emitted JavaScript')
        code = subprocess.check_output([str(self.after), 'emit'], text=True, timeout=10)
        javascript = ('const Module={}; const $0=8,$1=128,$2=128,$3=3000,'
                      '$4=3000,$5=1024,$6=1984;\n' + code +
                      '\nconsole.log(JSON.stringify(Module.MapleBenchSimulationTiming));')
        result = subprocess.run(['node', '-e', javascript], capture_output=True,
                                text=True, check=True, timeout=10)
        value = json.loads(result.stdout)
        self.assertEqual(value['pending_ms'], 1984)
        self.assertTrue(value['catchup_limited'])
        self.assertEqual(value['max_updates_per_frame'], 128)

    def test_timer_uses_monotonic_clock(self):
        source = self.directory / 'src/client'
        singleton = source / 'Template/Singleton.h'
        singleton.parent.mkdir(exist_ok=True)
        singleton.write_text('namespace jrc { template<class T> struct Singleton {}; }\n')
        unit = self.directory / 'clock.cpp'
        unit.write_text('#include <chrono>\n#include <cstdint>\n#define private public\n'
                        '#include "Timer.h"\n#undef private\n'
                        'static_assert(jrc::Timer::clock::is_steady);\nint main() {}\n')
        subprocess.run([shutil.which('c++'), '-std=c++17', '-I', str(source), str(unit),
                        '-o', str(self.directory / 'clock')], capture_output=True,
                       check=True, timeout=20)


if __name__ == '__main__':
    unittest.main()
