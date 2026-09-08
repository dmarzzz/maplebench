"""Compile the production ammo policy with projectile-class boundary cases."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AmmunitionPolicyTest(unittest.TestCase):
    def test_bow_buff_and_other_projectile_boundaries(self):
        compiler = shutil.which('c++')
        if not compiler:
            self.skipTest('C++ compiler required')
        source = r'''
#include "AmmunitionPolicy.h"
#include <cassert>
int main() {
 using namespace jrc;
 // Buff supplies ammunition for both basic and skill attack validation.
 assert(effective_ammunition(0,true,true)>=1);
 assert(effective_ammunition(0,true,true)>=10);
 assert(has_ranged_projectile(false,true,true));
 // Expired/missing Soul Arrow must not authorize empty projectile attacks.
 assert(effective_ammunition(0,true,false)==0);
 assert(!has_ranged_projectile(false,true,false));
 // Claws/guns never inherit a bow buff exemption.
 assert(effective_ammunition(0,false,true)==0);
 assert(!has_ranged_projectile(false,false,true));
 assert(effective_ammunition(7,false,true)==7);
 assert(has_ranged_projectile(true,false,false));
 assert(projectile_visual(0,true,false,true)==2060000);
 assert(projectile_visual(0,false,true,true)==2061000);
 assert(projectile_visual(2060001,true,false,true)==2060001);
 assert(projectile_visual(0,true,false,false)==0);
 assert(projectile_visual(0,false,false,true)==0);
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'test.cpp').write_text(source)
            subprocess.run([compiler,'-std=c++11','-Wall','-Wextra','-Werror','-I',str(ROOT/'patches/full-client'),str(p/'test.cpp'),'-o',str(p/'test')],check=True,capture_output=True,timeout=20)
            subprocess.run([str(p/'test')],check=True,capture_output=True,timeout=5)
