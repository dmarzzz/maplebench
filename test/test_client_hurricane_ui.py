"""Compile real UI focus cancellation bodies; verify release precedes UI routing."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from test_client_hurricane_channel import method
ROOT=Path(__file__).resolve().parents[1]
FIXTURE=ROOT/'test/fixtures/client-hurricane-channel'

class HurricaneUITest(unittest.TestCase):
 def test_focus_loss_disable_and_textfield_cancel_without_restart(self):
  compiler=shutil.which('c++')
  if not compiler:self.skipTest('C++ compiler required')
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);shutil.copytree(FIXTURE,root/'src/client')
   subprocess.run(['patch','-p1','--batch','-i',str(ROOT/'patches/full-client/0018-hurricane-channel.patch')],cwd=root,check=True,capture_output=True,timeout=5)
   source=(root/'src/client/IO/UI.cpp').read_text()
   routing=method(source,'void UI::send_key')
   self.assertLess(routing.index('send_skill_key(mapping.action, false)'),routing.index('if (focusedtextfield)'))
   self.assertLess(routing.index('send_skill_key(mapping.action, false)'),routing.index('if (escape)'))
   self.assertIn('else if (keycode == GLFW_KEY_ESCAPE)',routing)
   code=r'''
#include <cassert>
namespace jrc {
struct Combat {bool active=true;int cancels=0;void cancel_channel(){active=false;++cancels;}};
struct Stage {Combat combat;static Stage&get(){static Stage s;return s;}Combat&get_combat(){return combat;}};
struct Textfield {enum State {NORMAL};void set_state(State){}};
struct SFXVolume{};struct BGMVolume{};
template<class T>struct Setting {static Setting&get(){static Setting x;return x;}int load(){return 10;}};
struct Sound {static void set_sfxvolume(int){}};struct Music{static void set_bgmvolume(int){}};
struct UI {bool enabled=true;Textfield* focusedtextfield=nullptr;void disable();void send_focus(int);void focus_textfield(Textfield*);};
'''
   code+='\n'.join(method(source,s) for s in ['void UI::disable','void UI::send_focus','void UI::focus_textfield'])
   code+=r'''
}
int main(){using namespace jrc;UI ui;Combat&c=Stage::get().combat;
 ui.send_focus(0);assert(!c.active&&c.cancels==1);
 ui.send_focus(1);assert(!c.active&&c.cancels==1);
 c.active=true;ui.disable();assert(!c.active&&!ui.enabled);
 c.active=true;Textfield t;ui.focus_textfield(&t);assert(!c.active&&ui.focusedtextfield==&t);
}
'''
   p=root/'ui.cpp';p.write_text(code)
   result=subprocess.run([compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(p),'-o',str(root/'ui')],capture_output=True,text=True,timeout=20)
   self.assertEqual(result.returncode,0,result.stderr)
   subprocess.run([str(root/'ui')],check=True,capture_output=True,timeout=5)
